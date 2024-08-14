from datetime import date, datetime
import json
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST
from common.models import Assets, Brokers, Transactions
from common.forms import DashboardForm
from utils import broker_group_to_ids, calculate_closed_table_output, get_last_exit_date_for_brokers

@login_required
def closed_positions(request):
    
    user = request.user

    effective_current_date = datetime.strptime(request.session['effective_current_date'], '%Y-%m-%d').date()
    
    currency_target = user.default_currency
    number_of_digits = user.digits
    use_default_currency = user.use_default_currency_where_relevant
    selected_brokers = broker_group_to_ids(user.custom_brokers, user)

    sidebar_padding = 0
    sidebar_width = 0
    brokers = Brokers.objects.filter(investor=request.user).all()

    sidebar_width = request.GET.get("width")
    sidebar_padding = request.GET.get("padding")

    initial_data = {
        'selected_brokers': selected_brokers,
        'default_currency': currency_target,
        'table_date': effective_current_date,
        'digits': number_of_digits
    }
    dashboard_form = DashboardForm(instance=request.user, initial=initial_data)

    # assets = Assets.objects.filter(
    #     investor=user,
    #     transactions__date__lte=effective_current_date,
    #     transactions__broker_id__in=selected_brokers,
    #     transactions__quantity__isnull=False
    # ).distinct()

    # portfolio_closed = []

    # for asset in assets:
    #     if len(asset.exit_dates(effective_current_date)) != 0:
    #         portfolio_closed.append(asset)

    # categories = ['investment_date', 'exit_date', 'realized_gl', 'capital_distribution', 'commission']

    # portfolio_closed, portfolio_closed_totals = calculate_closed_table_output(user.id, portfolio_closed,
    #                                                                effective_current_date,
    #                                                                categories,
    #                                                                use_default_currency,
    #                                                                currency_target,
    #                                                                selected_brokers,
    #                                                                number_of_digits
    #                                                                )
    
    buttons = ['transaction', 'broker', 'price', 'security', 'settings']
    
    first_year = Transactions.objects.filter(
        investor=user,
        broker__in=selected_brokers
    ).order_by('date').first()
    
    # Addressing empty broker
    if first_year:
        first_year = first_year.date.year

    last_exit_date = get_last_exit_date_for_brokers(selected_brokers, effective_current_date)
    last_year = last_exit_date.year if last_exit_date and last_exit_date.year < effective_current_date.year else effective_current_date.year - 1

    if first_year is not None:
        closed_table_years = list(range(first_year, last_year + 1))
    else:
        closed_table_years = []
    
    return render(request, 'closed_positions.html', {
        'sidebar_width': sidebar_width,
        'sidebar_padding': sidebar_padding,
        # 'portfolio_closed': portfolio_closed,
        # 'portfolio_closed_totals': portfolio_closed_totals,
        'brokers': brokers,
        'currency': currency_target,
        'table_date': effective_current_date,
        'number_of_digits': number_of_digits,
        'selectedBrokers': user.custom_brokers,
        'dashboardForm': dashboard_form,
        'buttons': buttons,
        'closed_table_years': closed_table_years,
    })

@require_POST
def update_closed_positions_table(request):
    data = json.loads(request.body)
    timespan = data.get('timespan')

    user = request.user
    effective_current_date = datetime.strptime(request.session['effective_current_date'], '%Y-%m-%d').date()
    
    currency_target = user.default_currency
    number_of_digits = user.digits
    use_default_currency = user.use_default_currency_where_relevant
    selected_brokers = broker_group_to_ids(user.custom_brokers, user)

    # Process the data based on the timespan
    if timespan == 'YTD':
        start_date = date(effective_current_date.year, 1, 1)
        end_date = effective_current_date
    elif timespan == 'All-time':
        start_date = None
        end_date = effective_current_date
    else:
        start_date = date(int(timespan), 1, 1)
        end_date = date(int(timespan), 12, 31)

    assets = Assets.objects.filter(
        investor=user,
        transactions__date__lte=end_date,
        transactions__broker_id__in=selected_brokers,
        transactions__quantity__isnull=False
    ).distinct()

    portfolio_closed = []

    for asset in assets:
        if len(asset.exit_dates(end_date)) != 0:
            portfolio_closed.append(asset)
    
    categories = ['investment_date', 'exit_date', 'realized_gl', 'capital_distribution', 'commission']

    portfolio_closed, portfolio_closed_totals = calculate_closed_table_output(user.id, portfolio_closed,
                                                                   end_date,
                                                                   categories,
                                                                   use_default_currency,
                                                                   currency_target,
                                                                   selected_brokers,
                                                                   number_of_digits,
                                                                   start_date
                                                                   )

    context = {
        'portfolio_closed': portfolio_closed,
        'portfolio_closed_totals': portfolio_closed_totals,
    }

    tbody_html = render_to_string('closed_positions_tbody.html', context)
    tfoot_html = render_to_string('closed_positions_tfoot.html', context)

    return JsonResponse({
        'ok': True,
        'tbody': tbody_html,
        'tfoot': tfoot_html,
    })

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.views.decorators.csrf import ensure_csrf_cookie
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q, F, ExpressionWrapper, FloatField, Case, When, Value

import logging
import re

logger = logging.getLogger(__name__)

import re

def convert_to_number(value):
    if isinstance(value, str):
        # Remove currency symbol, commas, and parentheses, then convert to float
        value = re.sub(r'[£,()]', '', value)
        return float(value) if value else 0
    elif isinstance(value, (int, float)):
        return value
    return 0  # Default value for non-numeric types

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@ensure_csrf_cookie
def get_closed_positions_table_api(request):
    data = request.data
    timespan = data.get('timespan')
    page = int(data.get('page', 1))
    items_per_page = int(data.get('items_per_page', 25))
    search = data.get('search', '')
    sort_by = data.get('sort_by', [])

    logger.debug(f"Received sorting parameters: sort_by={sort_by}")

    user = request.user
    effective_current_date = datetime.strptime(request.session['effective_current_date'], '%Y-%m-%d').date()
    currency_target = user.default_currency
    number_of_digits = user.digits
    use_default_currency = user.use_default_currency_where_relevant
    selected_brokers = broker_group_to_ids(user.custom_brokers, user)

    # Process the data based on the timespan
    if timespan == 'YTD':
        start_date = date(effective_current_date.year, 1, 1)
        end_date = effective_current_date
    elif timespan == 'All-time':
        start_date = None
        end_date = effective_current_date
    else:
        start_date = date(int(timespan), 1, 1)
        end_date = date(int(timespan), 12, 31)

    assets = Assets.objects.filter(
        investor=user,
        transactions__date__lte=end_date,
        transactions__broker_id__in=selected_brokers,
        transactions__quantity__isnull=False
    ).distinct()

    if search:
        assets = assets.filter(Q(name__icontains=search) | Q(type__icontains=search))

    portfolio_closed = []

    for asset in assets:
        if len(asset.exit_dates(end_date)) != 0:
            portfolio_closed.append(asset)
    
    categories = ['investment_date', 'exit_date', 'realized_gl', 'capital_distribution', 'commission']

    portfolio_closed, portfolio_closed_totals = calculate_closed_table_output(
        user.id, portfolio_closed, end_date, categories, use_default_currency,
        currency_target, selected_brokers, number_of_digits, start_date
    )

    ### Need to work on sorting function. As data is in string format with currencies, etc. and sometimes dates and strings

    if sort_by:
        def sort_key(item):
            return [
                (convert_to_number(item.get(sort['key'], 0)) if sort['key'] not in ['investment_date', 'exit_date'] else item.get(sort['key'], datetime.min.date()),
                 -1 if sort['order'] == 'desc' else 1)
                for sort in sort_by
            ]

        portfolio_closed = sorted(portfolio_closed, key=sort_key)

    logger.debug(f"Sort by: {sort_by}")
    logger.debug(f"Portfolio closed after sorting (first 5): {portfolio_closed[:5]}")
    logger.debug(f"Portfolio closed after sorting (last 5): {portfolio_closed[-5:]}")

    # Apply pagination
    paginator = Paginator(portfolio_closed, items_per_page)
    try:
        paginated_portfolio_closed = paginator.page(page)
    except PageNotAnInteger:
        paginated_portfolio_closed = paginator.page(1)
    except EmptyPage:
        paginated_portfolio_closed = paginator.page(paginator.num_pages)

    response_data = {
        'portfolio_closed': list(paginated_portfolio_closed),
        'portfolio_closed_totals': portfolio_closed_totals,
        'total_items': paginator.count,
        'current_page': page,
        'total_pages': paginator.num_pages,
    }

    logger.debug(f"Response data: {response_data}")

    return Response(response_data)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
@ensure_csrf_cookie
def get_year_options_api(request):
    user = request.user
    selected_brokers = broker_group_to_ids(user.custom_brokers, user)
    effective_current_date_str = request.session.get('effective_current_date')
    
    # Convert effective_current_date from string to date object
    effective_current_date = datetime.strptime(effective_current_date_str, '%Y-%m-%d').date() if effective_current_date_str else datetime.now().date()

    first_year = Transactions.objects.filter(
        investor=user,
        broker__in=selected_brokers
    ).order_by('date').first()
    
    if first_year:
        first_year = first_year.date.year

    last_exit_date = get_last_exit_date_for_brokers(selected_brokers, effective_current_date)
    last_year = last_exit_date.year if last_exit_date and last_exit_date.year < effective_current_date.year else effective_current_date.year - 1

    if first_year is not None:
        closed_table_years = list(range(first_year, last_year + 1))
    else:
        closed_table_years = []

    # Convert years to strings
    closed_table_years = [{'text': str(year), 'value': str(year)} for year in closed_table_years]

    # Add special options with a divider
    closed_table_years.extend([
        {'divider': True},
        {'text': 'All-time', 'value': 'All-time'},
        {'text': f'{effective_current_date.year}YTD', 'value': 'YTD'}
    ])

    return Response({
        'closed_table_years': closed_table_years,
    })