#!/bin/bash
# Script to start RabbitMQ and test the integration

echo "Starting RabbitMQ Redis Queue Integration..."
echo "=============================================="

# Check if podman-compose is available
if ! command -v podman-compose &> /dev/null; then
    echo "Error: podman-compose is not installed"
    exit 1
fi

# Start RabbitMQ service
echo "1. Starting RabbitMQ service..."
podman-compose up -d rabbitmq

# Wait for RabbitMQ to start
echo "2. Waiting for RabbitMQ to start (10 seconds)..."
sleep 10

# Check if RabbitMQ is running
echo "3. Checking RabbitMQ status..."
if podman-compose ps rabbitmq | grep -q "Up"; then
    echo "   ✅ RabbitMQ is running"
else
    echo "   ❌ RabbitMQ failed to start"
    echo "   Check logs: podman-compose logs rabbitmq"
    exit 1
fi

# Install dependencies if needed
echo "4. Installing Python dependencies..."
pip install -r requirements.txt

# Test the integration
echo "5. Testing RabbitMQ integration..."
python test_rabbitmq_redis.py

echo ""
echo "=============================================="
echo "RabbitMQ Redis Queue Integration Complete!"
echo ""
echo "Next steps:"
echo "1. Review the test output above"
echo "2. Start using RedisProducer in your code:"
echo ""
echo "   # Instead of direct Redis calls:"
echo "   # redis_client.set('key', 'value')"
echo ""
echo "   # Use the queue-based approach:"
echo "   from src.messaging.producers.redis_producer import get_redis_producer"
echo "   producer = await get_redis_producer()"
echo "   await producer.set_key('key', 'value', ttl=3600)"
echo ""
echo "3. Monitor RabbitMQ queues:"
echo "   http://localhost:15672 (admin/change-me-rabbitmq)"
echo ""
echo "4. To stop RabbitMQ:"
echo "   podman-compose stop rabbitmq"
echo ""
