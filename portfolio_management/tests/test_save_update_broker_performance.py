import pytest
from channels.testing import HttpCommunicator
from channels.db import database_sync_to_async
from database.consumers import UpdateAccountPerformanceConsumer
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from decimal import Decimal
from datetime import date, datetime, timedelta
from common.models import FX, AnnualPerformance, Brokers, BrokerAccounts, Transactions, Assets
from constants import (
    TRANSACTION_TYPE_BUY, TRANSACTION_TYPE_SELL, 
    TRANSACTION_TYPE_CASH_IN, TRANSACTION_TYPE_CASH_OUT
)
import json
import logging
from django.core.cache import cache
from asgiref.sync import sync_to_async

from core.portfolio_utils import get_last_exit_date_for_broker_accounts, calculate_performance

User = get_user_model()

@pytest.fixture
def user():
    """Create test user"""
    return User.objects.create_user(username='testuser', password='testpass')

@pytest.fixture
def broker(user):
    """Create test broker"""
    return Brokers.objects.create(name='Test Broker', investor=user)

@pytest.fixture
def broker_account(broker):
    """Create test broker account"""
    return BrokerAccounts.objects.create(
        broker=broker,
        name='Test Account',
        native_id='TEST001',
        restricted=False,
        is_active=True
    )

@pytest.fixture
def transactions(user, broker_account):
    """Create test transactions"""
    asset = Assets.objects.create(
        type='Stock',
        ISIN='US0378331005',
        name='Generic Security',
        currency='USD',
        exposure='Equity',
        restricted=False
    )
    asset.investors.add(user)

    Transactions.objects.create(
        investor=user,
        broker_account=broker_account,
        date=date(2022, 1, 1),
        type=TRANSACTION_TYPE_CASH_IN,
        cash_flow=Decimal('1500'),
        currency='USD'
    )
    Transactions.objects.create(
        investor=user,
        broker_account=broker_account,
        date=date(2022, 1, 2),
        type=TRANSACTION_TYPE_BUY,
        quantity=Decimal('10'),
        price=Decimal('100'),
        currency='USD',
        security=asset
    )
    Transactions.objects.create(
        investor=user,
        broker_account=broker_account,
        date=date(2022, 8, 31),
        type=TRANSACTION_TYPE_SELL,
        quantity=Decimal('-10'),
        price=Decimal('120'),
        currency='USD',
        security=asset
    )
    Transactions.objects.create(
        investor=user,
        broker_account=broker_account,
        date=date(2022, 9, 1),
        type=TRANSACTION_TYPE_CASH_OUT,
        cash_flow=Decimal('-1200'),
        currency='USD'
    )

@pytest.fixture
def fx_rates(user):
    # Create FX rates for the test period
    start_date = date(2010, 1, 1)
    # end_date = date(2023, 1, 1)
    # current_date = start_date
    # while current_date <= end_date:
    fx = FX.objects.create(date=start_date)
    fx.investors.add(user)
    fx.USDEUR = Decimal('1.15')
    fx.USDGBP = Decimal('1.25')
    fx.CHFGBP = Decimal('0.85')
    fx.RUBUSD = Decimal('65')
    fx.PLNUSD = Decimal('4')
    fx.save()
        # current_date += timedelta(days=1)

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_update_broker_performance_unauthorized(user, broker, broker_account):
    """Test unauthorized access"""
    session_id = 'test_session_123'
    update_data = {
        'user_id': user.id + 1,  # Different user ID
        'selection_account_type': 'broker',
        'selection_account_id': broker.id,
        'currency': 'USD',
        'is_restricted': 'False',
        'skip_existing_years': False,
        'effective_current_date': '2023-01-01'
    }
    
    await sync_to_async(cache.set)(f'account_performance_update_{session_id}', update_data)

    communicator = HttpCommunicator(
        UpdateAccountPerformanceConsumer.as_asgi(),
        "GET",
        f"/database/api/update-broker-performance/sse/?session_id={session_id}",
    )
    communicator.scope['user'] = user

    response = await communicator.get_response()
    
    assert response['status'] == 403
    response_data = json.loads(response['body'].decode('utf-8'))
    assert response_data['status'] == 'error'
    assert response_data['message'] == 'Unauthorized access to session'

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_update_broker_performance_missing_session(user, broker, broker_account):
    """Test missing session ID"""
    communicator = HttpCommunicator(
        UpdateAccountPerformanceConsumer.as_asgi(),
        "GET",
        "/database/api/update-broker-performance/sse/",  # No session_id
    )
    communicator.scope['user'] = user

    response = await communicator.get_response()
    
    assert response['status'] == 400
    response_data = json.loads(response['body'].decode('utf-8'))
    assert response_data['status'] == 'error'
    assert response_data['message'] == 'Session ID is required'

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_update_broker_performance_invalid_data(user):
    """Test broker performance calculation with invalid data"""
    # Use DRF's APIClient instead of Django's client
    client = APIClient()
    await sync_to_async(client.force_authenticate)(user=user)
    
    # Step 1: Test validation endpoint
    invalid_data = {
        'selection_account_type': 'invalid',
        'selection_account_id': 'INVALID',
        'currency': 'INVALID',
        'is_restricted': 'INVALID',
        'skip_existing_years': 'not_a_boolean',
        'effective_current_date': '2023-01-01'
    }
    
    # First, test the validation endpoint
    response = await sync_to_async(client.post)(
        '/database/api/update-account-performance/validate/',
        invalid_data,
        format='json'  # Use format='json' instead of content_type
    )
    
    assert response.status_code == 400
    response_data = response.json()
    assert response_data['valid'] is False
    assert response_data['type'] == 'validation'
    assert 'errors' in response_data
    
    # Verify specific validation errors
    errors = response_data['errors']
    assert 'selection_account_type' in errors  # Invalid account type
    assert 'currency' in errors  # Invalid currency
    assert 'is_restricted' in errors  # Invalid restriction value
    
    # Step 2: Test that invalid data can't start the process
    response = await sync_to_async(client.post)(
        '/database/api/update-account-performance/start/',
        invalid_data,
        format='json'
    )
    
    assert response.status_code == 400
    response_data = response.json()
    assert response_data['valid'] is False
    assert response_data['type'] == 'validation'

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_update_broker_performance_no_transactions(user, broker):
    """Test broker performance calculation with no transactions"""

    session_id = 'test_session_invalid'
    update_data = {
        'user_id': user.id,
        'selection_account_type': 'broker',
        'selection_account_id': broker.id,
        'currency': 'USD',
        'is_restricted': 'False',
        'skip_existing_years': False,
        'effective_current_date': '2023-01-01'
    }
    
    await sync_to_async(cache.set)(f'account_performance_update_{session_id}', update_data)

    communicator = HttpCommunicator(
        UpdateAccountPerformanceConsumer.as_asgi(),
        "GET",
        f"/database/api/update-account-performance/sse/?session_id={session_id}",
    )

    communicator.scope['user'] = user
    response = await communicator.get_response()
    
    assert response['status'] == 200
    
    # Parse SSE messages
    response_body = response['body'].decode('utf-8')
    events = [
        json.loads(line.replace('data: ', ''))
        for line in response_body.strip().split('\n\n')
        if line.startswith('data: ')
    ]

    error_events = [event for event in events if event['status'] == 'error']
    assert len(error_events) == 1
    assert error_events[0]['message'] == 'No transactions found'

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_update_broker_performance_streaming(user, broker, broker_account, transactions, fx_rates, capsys):
    """Test broker performance streaming with all currencies and restrictions"""
    print("Starting test_update_broker_performance_streaming")

    # Create session ID and cache the update data
    session_id = 'test_session_streaming'
    update_data = {
        'user_id': user.id,
        'selection_account_type': 'broker',
        'selection_account_id': broker.id,
        'currency': 'All',
        'is_restricted': 'All',
        'skip_existing_years': False,
        'effective_current_date': '2023-01-01'
    }
    
    await sync_to_async(cache.set)(f'account_performance_update_{session_id}', update_data)

    communicator = HttpCommunicator(
        UpdateAccountPerformanceConsumer.as_asgi(),
        "GET",
        f"/database/api/update-broker-performance/sse/?session_id={session_id}",
    )

    communicator.scope['user'] = user
    response = await communicator.get_response()
    
    assert response['status'] == 200

    events = [
        json.loads(msg.decode('utf-8').replace('data: ', ''))
        for msg in response['body'].split(b'\n\n')
        if msg.startswith(b'data: ')
    ]

    progress_events = [event for event in events if event['status'] == 'progress']
    complete_events = [event for event in events if event['status'] == 'complete']

    # Verify progress events contain required fields
    for event in progress_events:
        assert 'status' in event
        assert 'current' in event
        assert 'progress' in event
        assert 'year' in event
        assert 'currency' in event
        assert 'is_restricted' in event

    assert len(complete_events) == 1

    captured = capsys.readouterr()
    print("============== Captured output: ==============")
    print(captured.out)

@pytest.mark.django_db
def test_get_last_exit_date_for_brokers(user, broker_account):
    asset = Assets.objects.create(
        type='Stock',
        ISIN='US1234567890',
        name='Test Stock',
        currency='USD',
        exposure='Equity',
        restricted=False
    )
    asset.investors.add(user)
    
    transaction_date = datetime.now().date() - timedelta(days=30)
    Transactions.objects.create(
        investor=user,
        broker_account=broker_account,
        security=asset,
        date=transaction_date,
        type=TRANSACTION_TYPE_BUY,
        quantity=100,
        price=10,
        currency='USD'
    )
    
    current_date = datetime.now().date()
    last_exit_date = get_last_exit_date_for_broker_accounts([broker_account.id], current_date)
    
    assert last_exit_date == current_date

    # Close the position
    Transactions.objects.create(
        investor=user,
        broker_account=broker_account,
        security=asset,
        date=current_date - timedelta(days=1),
        type=TRANSACTION_TYPE_SELL,
        quantity=-100,
        price=15,
        currency='USD'
    )
    
    last_exit_date = get_last_exit_date_for_broker_accounts([broker_account.id], current_date)
    assert last_exit_date == current_date - timedelta(days=1)

@pytest.mark.django_db
def test_calculate_performance(user, broker_account, caplog):

    caplog.set_level(logging.DEBUG)
    
    asset = Assets.objects.create(
        type='Stock',
        ISIN='US1234567890',
        name='Test Stock',
        currency='USD',
        exposure='Equity',
        restricted=False
    )
    asset.investors.add(user)
    
    start_date = datetime(2022, 1, 1).date()
    end_date = datetime(2022, 12, 31).date()
    
    Transactions.objects.create(
        investor=user,
        broker_account=broker_account,
        date=start_date,
        type=TRANSACTION_TYPE_CASH_IN,
        cash_flow=Decimal('1000'),
        currency='USD'
    )
    Transactions.objects.create(
        investor=user,
        broker_account=broker_account,
        security=asset,
        date=start_date + timedelta(days=30),
        type=TRANSACTION_TYPE_BUY,
        quantity=100,
        price=10,
        currency='USD'
    )
    Transactions.objects.create(
        investor=user,
        broker_account=broker_account,
        security=asset,
        date=end_date - timedelta(days=30),
        type=TRANSACTION_TYPE_SELL,
        quantity=-100,
        price=15,
        currency='USD'
    )
    Transactions.objects.create(
        investor=user,
        broker_account=broker_account,
        date=end_date,
        type=TRANSACTION_TYPE_CASH_OUT,
        cash_flow=Decimal('-1200'),
        currency='USD'
    )
    
    performance_data = calculate_performance(
        user,
        start_date,
        end_date,
        'account',
        broker_account.id,
        'USD'
    )

    for t in Transactions.objects.filter(investor=user, broker_account=broker_account):
        print(f"Transaction: {t.date} {t.type} {t.quantity} {t.price} {t.currency}")

    print(f"Price change: {asset.realized_gain_loss(end_date, user, 'USD', broker_account_ids=[broker_account.id], start_date=start_date)}")
    
    assert 'bop_nav' in performance_data
    assert 'eop_nav' in performance_data
    assert 'invested' in performance_data
    assert 'cash_out' in performance_data
    assert 'price_change' in performance_data
    assert 'capital_distribution' in performance_data
    assert 'commission' in performance_data
    assert 'tax' in performance_data
    assert 'fx' in performance_data
    assert 'tsr' in performance_data
    
    assert performance_data['invested'] == Decimal('1000')  # No cash inflows
    assert performance_data['cash_out'] == Decimal('-1200')  # No cash outflows
    assert performance_data['price_change'] == Decimal('500')  # (15 - 10) * 100

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_update_broker_performance_skip_existing(user, broker, broker_account, caplog):
    """Test broker performance calculation with skip_existing_years=True"""
    print("\nStarting test_update_broker_performance_skip_existing")
    caplog.set_level(logging.INFO)
    
    # Create a new broker specifically for this test
    @database_sync_to_async
    def create_test_broker():
        return Brokers.objects.create(
            name='Test Broker Skip Existing',
            investor=user
        )
    
    test_broker = await create_test_broker()
    
    # Create a new broker account for this test
    @database_sync_to_async
    def create_test_account():
        return BrokerAccounts.objects.create(
            broker=test_broker,
            name='Test Account Skip Existing',
            native_id='TEST002',
            restricted=False,
            is_active=True
        )
    
    test_account = await create_test_account()
    
    # Create test data
    @database_sync_to_async
    def setup_test_data():
        # Create asset with unique ISIN
        asset = Assets.objects.create(
            type='Stock',
            ISIN='US0378331006',  # Different ISIN
            name='Test Stock Skip',
            currency='USD',
            exposure='Equity',
            restricted=False
        )
        asset.investors.add(user)
        
        # Create transactions using test_account
        years = [2021, 2022, 2023]
        for year in years:
            Transactions.objects.create(
                investor=user,
                broker_account=test_account,
                date=date(year, 1, 1),
                type=TRANSACTION_TYPE_CASH_IN,
                cash_flow=Decimal('1000'),
                currency='USD'
            )
            Transactions.objects.create(
                investor=user,
                broker_account=test_account,
                date=date(year, 6, 1),
                type=TRANSACTION_TYPE_BUY,
                quantity=Decimal('10'),
                price=Decimal('100'),
                currency='USD',
                security=asset
            )
            Transactions.objects.create(
                investor=user,
                broker_account=test_account,
                date=date(year, 12, 31),
                type=TRANSACTION_TYPE_SELL,
                quantity=Decimal('-10'),
                price=Decimal('120'),
                currency='USD',
                security=asset
            )

        # Create existing AnnualPerformance for 2022
        AnnualPerformance.objects.create(
            investor=user,
            account_type='broker',
            account_id=test_broker.id,
            year=2022,
            currency='USD',
            restricted=False,
            bop_nav=Decimal('1200'),
            eop_nav=Decimal('2400'),
            invested=Decimal('1000'),
            cash_out=Decimal('0'),
            price_change=Decimal('200'),
            capital_distribution=Decimal('0'),
            commission=Decimal('0'),
            tax=Decimal('0'),
            fx=Decimal('0'),
            tsr='20%'
        )

    await setup_test_data()
    print("Created transactions and existing AnnualPerformance")

    # Create session ID and cache the update data
    session_id = 'test_session_skip_existing'
    update_data = {
        'user_id': user.id,
        'selection_account_type': 'broker',
        'selection_account_id': test_broker.id,
        'currency': 'USD',
        'is_restricted': 'False',
        'skip_existing_years': True,
        'effective_current_date': '2024-01-01'
    }
    
    await sync_to_async(cache.set)(f'account_performance_update_{session_id}', update_data)

    communicator = HttpCommunicator(
        UpdateAccountPerformanceConsumer.as_asgi(),
        "GET",
        f"/database/api/update-broker-performance/sse/?session_id={session_id}",
    )

    communicator.scope['user'] = user
    response = await communicator.get_response()
    
    assert response['status'] == 200

    events = [
        json.loads(msg.decode('utf-8').replace('data: ', ''))
        for msg in response['body'].split(b'\n\n')
        if msg.startswith(b'data: ')
    ]

    progress_events = [event for event in events if event['status'] == 'progress']
    complete_events = [event for event in events if event['status'] == 'complete']

    print(f"Number of progress events: {len(progress_events)}")
    print(f"Number of complete events: {len(complete_events)}")

    assert len(progress_events) == 2  # Progress events for 2021 and 2023
    assert len(complete_events) == 1

    @database_sync_to_async
    def get_performances():
        return {
            '2022': AnnualPerformance.objects.filter(
                investor=user,
                account_type='broker',
                account_id=test_broker.id,
                year=2022,
                currency='USD',
                restricted=False
            ).first(),
            '2021': AnnualPerformance.objects.filter(
                investor=user,
                account_type='broker',
                account_id=test_broker.id,
                year=2021,
                currency='USD',
                restricted=False
            ).first(),
            '2023': AnnualPerformance.objects.filter(
                investor=user,
                account_type='broker',
                account_id=test_broker.id,
                year=2023,
                currency='USD',
                restricted=False
            ).first()
        }

    performances = await get_performances()

    # Check if 2022 performance was not updated
    assert performances['2022'] is not None
    assert performances['2022'].bop_nav == Decimal('1200')
    assert performances['2022'].eop_nav == Decimal('2400')
    assert performances['2022'].invested == Decimal('1000')
    assert performances['2022'].cash_out == Decimal('0')
    assert performances['2022'].price_change == Decimal('200')

    # Check 2021 performance
    assert performances['2021'] is not None
    assert performances['2021'].bop_nav == Decimal('0')
    assert performances['2021'].eop_nav == Decimal('1200')
    assert performances['2021'].invested == Decimal('1000')
    assert performances['2021'].cash_out == Decimal('0')
    assert performances['2021'].price_change == Decimal('200')

    # Check 2023 performance
    assert performances['2023'] is not None
    assert performances['2023'].bop_nav == Decimal('2400')
    assert performances['2023'].eop_nav == Decimal('3600')
    assert performances['2023'].invested == Decimal('1000')
    assert performances['2023'].cash_out == Decimal('0')
    assert performances['2023'].price_change == Decimal('200')

@pytest.mark.django_db(transaction=True)  # Use transaction=True to avoid db locks
@pytest.mark.asyncio
async def test_update_broker_performance_initial(user, broker, broker_account, transactions, caplog):
    """Test initial broker performance calculation"""
    caplog.set_level(logging.INFO)
    
    # Create a unique session ID for this test
    session_id = 'test_initial_123'
    
    # Clean up any existing performance records for this broker
    @database_sync_to_async
    def cleanup_performances():
        AnnualPerformance.objects.filter(
            investor=user,
            account_type='broker',
            account_id=broker.id
        ).delete()
    
    await cleanup_performances()
    
    update_data = {
        'user_id': user.id,
        'selection_account_type': 'broker',
        'selection_account_id': broker.id,
        'currency': 'USD',
        'is_restricted': 'False',
        'skip_existing_years': False,
        'effective_current_date': '2023-01-01'
    }
    
    await sync_to_async(cache.set)(f'account_performance_update_{session_id}', update_data)
    
    # Create communicator with session_id in query params
    communicator = HttpCommunicator(
        UpdateAccountPerformanceConsumer.as_asgi(),
        "GET",  # Changed to GET since we're using query params
        f"/database/api/update-broker-performance/sse/?session_id={session_id}",
    )
    communicator.scope['user'] = user

    response = await communicator.get_response()
    
    # Verify the response
    assert response['status'] == 200
    
    # Parse SSE messages from response body
    messages = [
        json.loads(msg.decode('utf-8').replace('data: ', ''))
        for msg in response['body'].split(b'\n\n')
        if msg.startswith(b'data: ')
    ]

    # Verify the messages
    assert any(msg['status'] == 'initializing' for msg in messages)
    assert any(msg['status'] == 'progress' for msg in messages)
    assert any(msg['status'] == 'complete' for msg in messages)

    # Get performance record
    # Verify performance records
    @database_sync_to_async
    def get_performance_count():
        return AnnualPerformance.objects.filter(
            investor=user,
            account_type='broker',
            account_id=broker.id,
            currency='USD',
            restricted=False,
        ).count()

    @database_sync_to_async
    def get_performance():
        return AnnualPerformance.objects.get(
            investor=user,
            account_type='broker',
            account_id=broker.id,
            currency='USD',
            restricted=False,
        )
    
    # First verify we have exactly one record
    count = await get_performance_count()
    assert count == 1

    performance = await get_performance()
    
    # Verify performance record
    assert performance is not None
    assert performance.bop_nav == Decimal('0')
    assert performance.eop_nav == Decimal('500')
    assert performance.invested == Decimal('1500')
    assert performance.cash_out == Decimal('-1200')
    assert performance.price_change == Decimal('200')
