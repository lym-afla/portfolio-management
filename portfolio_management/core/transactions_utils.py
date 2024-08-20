from datetime import datetime
from decimal import Decimal
from itertools import chain
from operator import attrgetter
from typing import List, Dict, Any

from django.db.models import Q
from common.models import Brokers, FXTransaction, Transactions
from utils import broker_group_to_ids
from .date_utils import get_date_range
from .formatting_utils import format_table_data, currency_format
from .pagination_utils import paginate_table

def get_transactions_table_api(request):
    data = request.data
    timespan = data.get('timespan', '')
    page = int(data.get('page', 1))
    items_per_page = int(data.get('items_per_page', 25))
    search = data.get('search', '')

    print(f"transaction_utils. 21. timespan: {timespan}, page: {page}, items_per_page: {items_per_page}, search: {search}")

    user = request.user
    effective_current_date = datetime.strptime(request.session['effective_current_date'], '%Y-%m-%d').date()

    currency_target = user.default_currency
    number_of_digits = user.digits
    selected_brokers = broker_group_to_ids(user.custom_brokers, user)

    start_date, end_date = get_date_range(timespan, effective_current_date)

    transactions = _filter_transactions(user, start_date, end_date, selected_brokers, search)
    
    transactions_data = calculate_transactions_table_output(
        user, transactions, selected_brokers, number_of_digits
    )

    paginated_transactions, pagination_data = paginate_table(transactions_data, page, items_per_page)

    formatted_transactions = format_table_data(paginated_transactions, currency_target, number_of_digits)

    return {
        'transactions': formatted_transactions,
        'total_items': pagination_data['total_items'],
        'current_page': pagination_data['current_page'],
        'total_pages': pagination_data['total_pages'],
    }

def _filter_transactions(user, start_date, end_date, selected_brokers, search):
    transactions_query = Transactions.objects.filter(
        investor=user,
        date__range=(start_date, end_date),
        broker_id__in=selected_brokers
    ).select_related('broker', 'security')

    fx_transactions_query = FXTransaction.objects.filter(
        investor=user,
        date__range=(start_date, end_date),
        broker_id__in=selected_brokers
    ).select_related('broker')

    if search:
        transactions_query = transactions_query.filter(
            Q(security__name__icontains=search) | 
            Q(type__icontains=search)
        )
        fx_transactions_query = fx_transactions_query.filter(
            Q(from_currency__icontains=search) | 
            Q(to_currency__icontains=search)
        )

    all_transactions = sorted(
        chain(transactions_query, fx_transactions_query),
        key=attrgetter('date')
    )

    return all_transactions

def calculate_transactions_table_output(user, transactions, selected_brokers, number_of_digits):
    currencies = set()
    for broker in Brokers.objects.filter(investor=user, id__in=selected_brokers):
        currencies.update(broker.get_currencies())

    balance = {currency: Decimal(0) for currency in currencies}
    transactions_data = []
    
    for transaction in transactions:
        transaction_data = {}
        transaction_data['date'] = transaction.date
        transaction_data['balances'] = {}

        if isinstance(transaction, Transactions):
            transaction_data.update(_process_regular_transaction(transaction, balance, currencies, number_of_digits))
        elif isinstance(transaction, FXTransaction):
            transaction_data.update(_process_fx_transaction(transaction, balance, currencies, number_of_digits))

        for currency in currencies:
            transaction_data['balances'][currency] = currency_format(balance[currency], currency, number_of_digits)

        transactions_data.append(transaction_data)
    
    return transactions_data

def _process_regular_transaction(transaction, balance, currencies, number_of_digits):
    transaction_data = {
        'type': transaction.type,
        'security': transaction.security.name if transaction.security else None,
        'currency': transaction.currency,
    }

    balance[transaction.currency] = balance.get(transaction.currency, Decimal(0)) - Decimal((transaction.price or 0) * Decimal(transaction.quantity or 0) \
        - Decimal(transaction.cash_flow or 0) \
        - Decimal(transaction.commission or 0))

    if transaction.quantity:
        transaction_data['value'] = currency_format(-round(Decimal(transaction.quantity * transaction.price), 2) + (transaction.commission or 0), transaction.currency, number_of_digits)
        transaction_data['price'] = currency_format(transaction.price, transaction.currency, number_of_digits)
        transaction_data['quantity'] = abs(round(transaction.quantity, 0))
    if transaction.cash_flow:
        transaction_data['cash_flow'] = currency_format(transaction.cash_flow, transaction.currency, number_of_digits)
    if transaction.commission:
        transaction_data['commission'] = currency_format(-transaction.commission, transaction.currency, number_of_digits)

    return transaction_data

def _process_fx_transaction(transaction, balance, currencies, number_of_digits):
    transaction_data = {
        'type': 'FX',
        'from_currency': transaction.from_currency,
        'to_currency': transaction.to_currency,
    }

    balance[transaction.from_currency] -= transaction.from_amount
    balance[transaction.to_currency] += transaction.to_amount
    if transaction.commission:
        balance[transaction.from_currency] -= transaction.commission

    transaction_data['from_amount'] = currency_format(-transaction.from_amount, transaction.from_currency, number_of_digits)
    transaction_data['to_amount'] = currency_format(transaction.to_amount, transaction.to_currency, number_of_digits)
    if transaction.commission:
        transaction_data['commission'] = currency_format(-transaction.commission, transaction.from_currency, number_of_digits)

    return transaction_data