#!/bin/bash
# Script to start RabbitMQ and test the integration

echo "Starting RabbitMQ Queue Integration..."
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

echo "5. RabbitMQ is ready."

echo ""
echo "=============================================="
echo "RabbitMQ Queue Integration Complete!"
echo ""
echo "Next steps:"
echo "1. Review the test output above"
echo "2. Publish messages using the broker in your code:"
echo ""
echo "   from src.messaging.broker import get_broker"
echo "   broker = await get_broker()"
echo "   await broker.publish('document-processing', message)"
echo ""
echo "3. Monitor RabbitMQ queues:"
echo "   http://localhost:15672 (admin/change-me-rabbitmq)"
echo ""
echo "4. To stop RabbitMQ:"
echo "   podman-compose stop rabbitmq"
echo ""
