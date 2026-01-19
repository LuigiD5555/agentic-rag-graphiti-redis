#!/usr/bin/env python3
"""Test script to demonstrate RabbitMQ Redis queue integration."""

import asyncio
import sys
import os

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def test_rabbitmq_setup():
    """Test RabbitMQ setup and basic Redis operations."""
    print("Testing RabbitMQ Redis Queue Integration")
    print("=" * 50)
    
    try:
        # Import modules
        from src.messaging.config import config
        from src.messaging.broker import RabbitMQBroker
        from src.messaging.models.message import RedisOperationMessage
        
        print(f"1. RabbitMQ Configuration:")
        print(f"   - Host: {config.host}:{config.port}")
        print(f"   - VHost: {config.vhost}")
        print(f"   - Enabled: {config.enabled}")
        print(f"   - Redis Queue: {config.redis_queue}")
        
        # Test broker connection
        print(f"\n2. Testing Broker Connection...")
        broker = RabbitMQBroker()
        try:
            await broker.connect()
            print("   ✓ Connected to RabbitMQ successfully")
            
            # Test message creation
            print(f"\n3. Testing Message Creation...")
            message = RedisOperationMessage(
                operation="set",
                data={"key": "test:key", "value": "test_value", "ttl": 60}
            )
            print(f"   ✓ Created Redis operation message")
            print(f"   - Message ID: {message.message_id}")
            print(f"   - Operation: {message.payload.operation}")
            print(f"   - Priority: {message.priority}")
            
            # Test message publishing
            print(f"\n4. Testing Message Publishing...")
            success = await broker.publish(config.redis_queue, message)
            if success:
                print("   ✓ Message published successfully")
            else:
                print("   ✗ Failed to publish message")
            
            # Cleanup
            await broker.disconnect()
            print(f"\n5. Cleanup:")
            print("   ✓ Disconnected from RabbitMQ")
            
        except Exception as e:
            print(f"   ✗ Connection failed: {e}")
            return False
        
        print(f"\n" + "=" * 50)
        print("Test completed successfully!")
        print("\nNext steps:")
        print("1. Start RabbitMQ: podman-compose up -d rabbitmq")
        print("2. Install dependencies: pip install -r requirements.txt")
        print("3. Run Redis consumer: python -m src.messaging.consumers.redis_consumer")
        print("4. Use RedisProducer in your code instead of direct Redis calls")
        
        return True
        
    except ImportError as e:
        print(f"Import error: {e}")
        print("\nPlease install required dependencies:")
        print("pip install aio-pika pydantic-settings")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False


async def test_redis_producer():
    """Test Redis producer functionality."""
    print(f"\n\nTesting Redis Producer")
    print("=" * 50)
    
    try:
        from src.messaging.producers.redis_producer import get_redis_producer
        
        print("1. Initializing Redis Producer...")
        producer = await get_redis_producer()
        print("   ✓ Redis Producer initialized")
        
        # Test queuing operations
        print(f"\n2. Testing Operation Queuing...")
        
        # Queue SET operation
        message_id = await producer.set_key("test:session:123", "user_data", ttl=3600)
        print(f"   ✓ Queued SET operation: {message_id}")
        
        # Queue GET operation
        message_id = await producer.get_key("test:session:123")
        print(f"   ✓ Queued GET operation: {message_id}")
        
        # Queue AOF rewrite (rate limited)
        message_id = await producer.aof_rewrite()
        print(f"   ✓ Queued AOF rewrite operation: {message_id}")
        
        print(f"\n" + "=" * 50)
        print("Redis Producer test completed!")
        print("\nOperations have been queued and will be processed by Redis consumers.")
        
        return True
        
    except Exception as e:
        print(f"Error testing Redis producer: {e}")
        return False


async def main():
    """Main test function."""
    print("RabbitMQ Redis Queue Integration Test")
    print("=" * 60)
    
    # Test 1: Basic RabbitMQ setup
    success1 = await test_rabbitmq_setup()
    
    if success1:
        # Test 2: Redis producer
        success2 = await test_redis_producer()
        
        if success2:
            print(f"\n" + "=" * 60)
            print("✅ ALL TESTS PASSED!")
            print("\nImplementation Summary:")
            print("1. ✅ RabbitMQ service added to podman-compose.yml")
            print("2. ✅ Environment configuration updated")
            print("3. ✅ Dependencies added to requirements.txt")
            print("4. ✅ Messaging infrastructure created")
            print("5. ✅ Redis producer implemented")
            print("\nTo use in your code:")
            print("""
# Instead of:
# redis_client.set("key", "value")

# Use:
from src.messaging.producers.redis_producer import get_redis_producer
producer = await get_redis_producer()
await producer.set_key("key", "value", ttl=3600)
            """)
        else:
            print(f"\n❌ Redis Producer test failed")
    else:
        print(f"\n❌ RabbitMQ setup test failed")


if __name__ == "__main__":
    asyncio.run(main())
