import pytest
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from django.contrib.auth import get_user_model
from tinkoff.invest import OperationType, MoneyValue, Quotation

from core.tinkoff_utils import (
    get_read_only_token,
    get_security_by_uid,
    find_or_create_security,
    map_tinkoff_operation_to_transaction
)
from common.models import Assets, Brokers, Transactions
from constants import (
    TRANSACTION_TYPE_BUY,
    TRANSACTION_TYPE_SELL,
    TRANSACTION_TYPE_DIVIDEND,
    TRANSACTION_TYPE_BROKER_COMMISSION,
)

CustomUser = get_user_model()

@pytest.fixture
def user():
    return CustomUser.objects.create_user(
        username='testuser',
        email='test@example.com',
        password='testpass123'
    )

@pytest.fixture
def broker(user):
    return Brokers.objects.create(
        investor=user,
        name='Test Broker',
        country='Test Country'
    )

@pytest.fixture
def asset(user, broker):
    asset = Assets.objects.create(
        type='Stock',
        ISIN='TEST123456789',
        name='Test Stock',
        currency='USD',
        exposure='Equity'
    )
    asset.investors.add(user)
    asset.brokers.add(broker)
    return asset

@pytest.mark.asyncio
@patch('core.tinkoff_utils.Client')
async def test_get_security_by_uid(mock_client):
    # Mock the Tinkoff API response
    mock_instrument = MagicMock()
    mock_instrument.instrument.name = 'Test Stock'
    mock_instrument.instrument.isin = 'TEST123456789'

    mock_client_instance = MagicMock()
    mock_client_instance.instruments.get_instrument_by.return_value = mock_instrument
    mock_client.return_value.__enter__.return_value = mock_client_instance

    name, isin = await get_security_by_uid('test-uid')

    assert name == 'Test Stock'
    assert isin == 'TEST123456789'
    mock_client_instance.instruments.get_instrument_by.assert_called_once_with(
        id_type=3,
        id='test-uid'
    )

@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@patch('core.tinkoff_utils.get_security_by_uid')
async def test_find_or_create_security_with_relationships(mock_get_security, user, broker):
    mock_get_security.return_value = ('Test Stock', 'TEST123456789')
    asset = await Assets.objects.acreate(
        type='Stock',
        ISIN='TEST123456789',
        name='Test Stock',
        currency='USD',
        exposure='Equity'
    )
    await asset.investors.aset([user])
    await asset.brokers.aset([broker])

    security, status = await find_or_create_security('test-uid', user, broker)
    assert status == 'existing_with_relationships'
    assert security.ISIN == 'TEST123456789'

@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@patch('core.tinkoff_utils.get_security_by_uid')
async def test_find_or_create_security_without_relationships(mock_get_security, user, broker):
    mock_get_security.return_value = ('Test Stock', 'TEST123456789')
    asset = await Assets.objects.acreate(
        type='Stock',
        ISIN='TEST123456789',
        name='Test Stock',
        currency='USD',
        exposure='Equity'
    )

    security, status = await find_or_create_security('test-uid', user, broker)
    assert status == 'existing_added_relationships'
    assert security.ISIN == 'TEST123456789'

@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@patch('core.import_utils.requests.get')
@patch('core.import_utils.create_security_from_micex')
@patch('core.tinkoff_utils.get_security_by_uid')
async def test_find_or_create_security_new(mock_get_security, mock_create_security, mock_requests_get, user, broker):
    # First, ensure no assets exist with this ISIN
    await Assets.objects.filter(ISIN='NEW123456789').adelete()

    # Mock MICEX API responses
    mock_securities_response = MagicMock()
    mock_securities_response.status_code = 200
    mock_securities_response.json.return_value = {
        'securities': {
            'columns': ['SECID', 'ISIN', 'SECNAME', 'CURRENCYID'],
            'data': [['NEW', 'NEW123456789', 'New Stock', 'USD']]
        }
    }

    mock_detail_response = MagicMock()
    mock_detail_response.status_code = 200
    mock_detail_response.json.return_value = {
        'securities': {
            'columns': ['SECID', 'ISIN', 'SECNAME', 'CURRENCYID'],
            'data': [['NEW', 'NEW123456789', 'New Stock', 'USD']]
        }
    }

    # Set up requests.get to return our mock responses
    mock_requests_get.side_effect = [mock_securities_response, mock_detail_response]

    # Set up the mocks
    mock_get_security.return_value = ('New Stock', 'NEW123456789')

    # Create a mock asset without saving it to the database
    mock_asset = MagicMock(spec=Assets)
    mock_asset.ISIN = 'NEW123456789'
    mock_asset.name = 'New Stock'
    mock_asset.type = 'Stock'
    mock_asset.currency = 'USD'
    mock_asset.exposure = 'Equity'

    # Set up the mock to return our mock asset
    mock_create_security.return_value = mock_asset

    security, status = await find_or_create_security('test-uid', user, broker)
    assert status == 'created_new'
    assert security.ISIN == 'NEW123456789'

@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@patch('core.tinkoff_utils.find_or_create_security')
async def test_map_tinkoff_operation_to_transaction(mock_find_or_create, user, broker, asset):
    # Create mock operation
    operation = MagicMock()
    operation.date = datetime.now(timezone.utc)
    operation.description = 'Test transaction'
    operation.type = OperationType.OPERATION_TYPE_BUY
    operation.payment = MoneyValue(currency='USD', units=-100, nano=0)
    operation.price = Quotation(units=50, nano=0)
    operation.quantity = 2
    operation.commission = MoneyValue(currency='USD', units=1, nano=0)
    operation.instrument_uid = 'test-uid'

    mock_find_or_create.return_value = (asset, 'existing_with_relationships')

    # Test buy operation
    transaction_data = await map_tinkoff_operation_to_transaction(operation, user, broker)
    
    assert transaction_data['type'] == TRANSACTION_TYPE_BUY
    assert transaction_data['currency'] == 'USD'
    assert transaction_data['quantity'] == Decimal('2')
    assert transaction_data['price'] == Decimal('50')
    assert transaction_data['cash_flow'] == Decimal('-100')
    assert transaction_data['commission'] == Decimal('1')
    assert transaction_data['security'] == asset

    # Test sell operation
    operation.type = OperationType.OPERATION_TYPE_SELL
    operation.payment = MoneyValue(currency='USD', units=100, nano=0)
    
    transaction_data = await map_tinkoff_operation_to_transaction(operation, user, broker)
    assert transaction_data['type'] == TRANSACTION_TYPE_SELL
    assert transaction_data['cash_flow'] == Decimal('100')

@pytest.mark.asyncio
@patch('core.tinkoff_utils.open')
async def test_get_read_only_token(mock_open):
    # Test successful token retrieval
    mock_open.return_value.__enter__.return_value.read.return_value = '{"TOKEN_READ_ONLY": "test-token"}'
    token = get_read_only_token()
    assert token == 'test-token'

    # Test missing file
    mock_open.side_effect = FileNotFoundError()
    with pytest.raises(FileNotFoundError):
        get_read_only_token()

    # Test missing token in file
    mock_open.side_effect = None
    mock_open.return_value.__enter__.return_value.read.return_value = '{}'
    with pytest.raises(KeyError):
        get_read_only_token()

@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@patch('core.import_utils.create_security_from_micex')
@patch('core.tinkoff_utils.get_security_by_uid')
async def test_find_or_create_security_micex_failure(mock_get_security, mock_create_security, user, broker):
    mock_get_security.return_value = ('Test Stock', 'TEST123456789')
    mock_create_security.return_value = None  # Simulate MICEX API failure
    
    security, status = await find_or_create_security('test-uid', user, broker)
    assert status == 'failed_to_create'
    assert security is None