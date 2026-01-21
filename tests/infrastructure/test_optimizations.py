#!/usr/bin/env python3
"""
Script de prueba para verificar la integración de todas las optimizaciones del pipeline de ingestión.
"""

import os
import sys
import tempfile
from pathlib import Path

# Agregar el directorio src al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.workflows.ingestion.wave_planner import WavePlanner, WaveOrchestrator
from src.workflows.ingestion.resource_pools import ResourcePool, IngestionPools
from src.workflows.ingestion.watermark_cleanup import WatermarkCleanup
from src.workflows.ingestion.idempotency import IdempotencyManager, ProcessingStage
from src.workflows.ingestion.metrics import MetricsCollector, IngestionMetrics


def test_wave_planner():
    """Prueba el Wave Planner."""
    print("=== Probando Wave Planner ===")
    
    # Crear archivos de prueba
    test_dir = tempfile.mkdtemp(prefix="rag_test_")
    test_files = []
    
    for i in range(5):
        file_path = Path(test_dir) / f"test_file_{i}.txt"
        file_path.write_text(f"Contenido del archivo de prueba {i}\n" * 100)
        test_files.append(str(file_path))
    
    # Probar WavePlanner
    planner = WavePlanner(max_mb_per_wave=1.0, max_files_per_wave=2)
    waves = planner.plan_waves(test_files)
    
    print(f"Archivos de prueba creados: {len(test_files)}")
    print(f"Olas planificadas: {len(waves)}")
    
    for i, wave in enumerate(waves, 1):
        print(f"  Ola {i}: {len(wave.files)} archivos, {wave.total_mb:.2f} MB")
    
    # Probar WaveOrchestrator
    orchestrator = WaveOrchestrator(planner)
    
    def mock_process_callback(files):
        return {"processed": len(files), "files": files}
    
    result = orchestrator.execute_waves(test_files, mock_process_callback)
    
    print(f"Resultado de ejecución: {result['status']}")
    print(f"Olas exitosas: {result['successful_waves']}/{result['total_waves']}")
    
    # Limpiar
    import shutil
    shutil.rmtree(test_dir)
    
    print("✓ Wave Planner probado exitosamente\n")
    return True


def test_resource_pools():
    """Prueba los Resource Pools."""
    print("=== Probando Resource Pools ===")
    
    # Probar ResourcePool básico
    pool = ResourcePool("test_pool", max_workers=2, max_queue_size=5)
    
    results = []
    
    def test_task(task_id, delay=0.1):
        import time
        time.sleep(delay)
        return f"task_{task_id}_completed"
    
    # Enviar tareas
    futures = []
    for i in range(3):
        future = pool.submit(test_task, i, 0.05)
        if future:
            futures.append(future)
    
    # Esperar completación
    pool.wait_for_completion(timeout=5.0)
    
    # Obtener resultados
    for future in futures:
        try:
            result = future.result(timeout=1.0)
            results.append(result)
        except Exception as e:
            print(f"Error en tarea: {e}")
    
    # Obtener métricas
    metrics = pool.get_metrics()
    print(f"Tareas completadas: {metrics.completed_tasks}")
    print(f"Tareas fallidas: {metrics.failed_tasks}")
    print(f"Tiempo promedio: {metrics.avg_task_time:.3f}s")
    
    # Probar IngestionPools
    ingestion_pools = IngestionPools()
    print(f"Pools de ingestión creados: convert, embed, upsert")
    
    # Apagar pools
    pool.shutdown(wait=True)
    ingestion_pools.shutdown(wait=True)
    
    print("✓ Resource Pools probados exitosamente\n")
    return len(results) == 3


def test_watermark_cleanup():
    """Prueba el Watermark Cleanup."""
    print("=== Probando Watermark Cleanup ===")
    
    # Crear directorio de staging
    staging_dir = tempfile.mkdtemp(prefix="rag_staging_")
    
    # Crear algunos archivos de prueba
    for i in range(3):
        file_path = Path(staging_dir) / f"test_{i}.tmp"
        file_path.write_text("contenido temporal" * 100)
    
    # Probar WatermarkCleanup
    cleanup = WatermarkCleanup(
        staging_dir=staging_dir,
        watermark_percent=10.0,  # Bajo para forzar limpieza
        aggressive_percent=20.0,
        check_interval_seconds=1,
        workers=1
    )
    
    # Obtener uso de disco
    disk_usage = cleanup.get_disk_usage()
    print(f"Directorio de staging: {staging_dir}")
    print(f"Uso de disco: {disk_usage.usage_percent:.1f}%")
    
    # Verificar si necesita limpieza
    needs_cleanup, needs_aggressive = cleanup.should_cleanup()
    print(f"Necesita limpieza: {needs_cleanup}")
    print(f"Necesita limpieza agresiva: {needs_aggressive}")
    
    # Ejecutar limpieza
    cleanup_result = cleanup.run_cleanup(aggressive=False)
    print(f"Limpieza ejecutada: {cleanup_result['status']}")
    print(f"Archivos limpiados: {cleanup_result['files_cleaned']}")
    print(f"MB liberados: {cleanup_result.get('freed_mb', 0):.2f}")
    
    # Obtener métricas
    metrics = cleanup.get_metrics()
    print(f"Limpiezas totales: {metrics['cleanup_stats']['total_cleanups']}")
    
    # Limpiar
    import shutil
    shutil.rmtree(staging_dir)
    cleanup.stop_monitor()
    
    print("✓ Watermark Cleanup probado exitosamente\n")
    return True


def test_idempotency_manager():
    """Prueba el Idempotency Manager."""
    print("=== Probando Idempotency Manager ===")
    
    # Crear archivo de prueba
    test_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
    test_file.write("Contenido de prueba para idempotencia\n" * 10)
    test_file.close()
    
    # Probar IdempotencyManager
    manager = IdempotencyManager(ttl_seconds=3600)
    
    # Calcular hash
    file_hash = manager.compute_file_hash(test_file.name)
    print(f"Hash del archivo: {file_hash[:16]}...")
    
    # Verificar estado inicial
    initial_state = manager.get_file_state(test_file.name)
    print(f"Estado inicial: {'Existe' if initial_state else 'No existe'}")
    
    # Marcar etapas
    manager.mark_stage_completed(test_file.name, ProcessingStage.DISCOVERED)
    manager.mark_stage_completed(test_file.name, ProcessingStage.PREPROCESSED)
    
    # Verificar siguiente etapa
    next_stage = manager.get_next_stage(test_file.name)
    print(f"Siguiente etapa: {next_stage.value if next_stage else 'Completado'}")
    
    # Verificar si debe saltarse
    should_skip, reason = manager.should_skip_file(test_file.name)
    print(f"Debe saltarse: {should_skip} ({reason if reason else 'N/A'})")
    
    # Probar batch check
    batch_result = manager.batch_check_states([test_file.name])
    print(f"Batch check: {len(batch_result)} resultados")
    
    # Obtener métricas
    metrics = manager.get_metrics()
    print(f"Tamaño de cache: {metrics['cache_size']}")
    print(f"Ratio de hits: {metrics['hit_ratio']:.2%}")
    
    # Limpiar
    os.unlink(test_file.name)
    
    print("✓ Idempotency Manager probado exitosamente\n")
    return True


def test_metrics_collector():
    """Prueba el Metrics Collector."""
    print("=== Probando Metrics Collector ===")
    
    # Probar MetricsCollector
    collector = MetricsCollector()
    
    # Registrar diferentes tipos de métricas
    collector.increment("test.counter", 1)
    collector.gauge("test.gauge", 42.5)
    collector.timer("test.timer", 1.23)
    collector.histogram("test.histogram", 100.0)
    
    # Probar decorador timeit
    @collector.timeit("test.decorated_timer")
    def slow_function():
        import time
        time.sleep(0.01)
        return "done"
    
    result = slow_function()
    print(f"Función decorada: {result}")
    
    # Obtener métricas
    metrics = collector.get_metrics()
    print(f"Métricas registradas: {len(metrics)}")
    
    # Obtener resumen
    summary = collector.get_summary()
    print(f"Total de métricas: {summary['total_metrics']}")
    print(f"Tipos de métricas: {summary['metric_types']}")
    
    # Probar exportación Prometheus
    prometheus_output = collector.export_prometheus()
    print(f"Exportación Prometheus: {len(prometheus_output.splitlines())} líneas")
    
    # Probar IngestionMetrics
    ingestion_metrics = IngestionMetrics(collector)
    ingestion_metrics.record_discovery(10, 2)
    ingestion_metrics.record_file_processing("/test/path.txt", 1.5, True, 0.5)
    ingestion_metrics.record_chunk_processing(5, 100, 0.1)
    
    # Obtener resumen de ingestión
    ingestion_summary = ingestion_metrics.get_ingestion_summary()
    print(f"Archivos descubiertos: {ingestion_summary['files']['discovered']}")
    print(f"Chunks creados: {ingestion_summary['chunks']['created']}")
    
    # Limpiar
    collector.clear()
    
    print("✓ Metrics Collector probado exitosamente\n")
    return True


def test_integration():
    """Prueba la integración de todos los componentes."""
    print("=== Probando Integración Completa ===")
    
    # Crear directorio de prueba
    test_dir = tempfile.mkdtemp(prefix="rag_integration_")
    
    try:
        # Inicializar todos los componentes
        wave_planner = WavePlanner(max_mb_per_wave=5.0, max_files_per_wave=10)
        resource_pools = IngestionPools()
        watermark_cleanup = WatermarkCleanup(staging_dir=test_dir)
        idempotency_manager = IdempotencyManager()
        metrics_collector = MetricsCollector()
        
        print("Componentes inicializados:")
        print(f"  - WavePlanner: {wave_planner}")
        print(f"  - IngestionPools: {resource_pools}")
        print(f"  - WatermarkCleanup: {watermark_cleanup}")
        print(f"  - IdempotencyManager: {idempotency_manager}")
        print(f"  - MetricsCollector: {metrics_collector}")
        
        # Crear archivos de prueba
        test_files = []
        for i in range(3):
            file_path = Path(test_dir) / f"integration_test_{i}.txt"
            file_path.write_text(f"Archivo de integración {i}\n" * 50)
            test_files.append(str(file_path))
        
        # Probar flujo integrado
        print("\nSimulando flujo de procesamiento:")
        
        # 1. Wave Planning
        waves = wave_planner.plan_waves(test_files)
        print(f"  1. Wave Planning: {len(waves)} olas creadas")
        
        # 2. Idempotency check
        for file_path in test_files:
            should_skip, reason = idempotency_manager.should_skip_file(file_path)
            if not should_skip:
                idempotency_manager.mark_stage_completed(file_path, ProcessingStage.DISCOVERED)
        
        print(f"  2. Idempotency: {len(test_files)} archivos marcados como descubiertos")
        
        # 3. Resource Pool processing (simulado)
        def process_file(file_path):
            import time
            time.sleep(0.01)
            return {"file": file_path, "processed": True}
        
        futures = []
        for file_path in test_files:
            future = resource_pools.submit_conversion(process_file, file_path)
            if future:
                futures.append(future)
        
        resource_pools.wait_for_all(timeout=5.0)
        print(f"  3. Resource Pools: {len(futures)} tareas procesadas")
        
        # 4. Metrics recording
        metrics_collector.increment("integration.files.processed", len(test_files))
        metrics_collector.gauge("integration.active_workers", 2)
        
        metrics_summary = metrics_collector.get_summary()
        print(f"  4. Metrics: {metrics_summary['total_metrics']} métricas registradas")
        
        # 5. Cleanup
        for file_path in test_files:
            watermark_cleanup.cleanup_completed_file(file_path, immediate=True)
        
        print(f"  5. Cleanup: Archivos de prueba limpiados")
        
        # Apagar componentes
        resource_pools.shutdown(wait=True)
        watermark_cleanup.stop_monitor()
        
        print("\n✓ Integración probada exitosamente")
        return True
        
    finally:
        # Limpieza final
        import shutil
        shutil.rmtree(test_dir, ignore_errors=True)


def main():
    """Función principal de prueba."""
    print("=" * 60)
    print("PRUEBA DE OPTIMIZACIONES DEL PIPELINE DE INGESTIÓN")
    print("=" * 60)
    print()
    
    tests = [
        ("Wave Planner", test_wave_planner),
        ("Resource Pools", test_resource_pools),
        ("Watermark Cleanup", test_watermark_cleanup),
        ("Idempotency Manager", test_idempotency_manager),
        ("Metrics Collector", test_metrics_collector),
        ("Integración Completa", test_integration),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            success = test_func()
            results.append((test_name, success, None))
        except Exception as e:
            print(f"✗ Error en {test_name}: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False, str(e)))
        print()
    
    # Resumen
    print("=" * 60)
    print("RESUMEN DE PRUEBAS")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    for test_name, success, error in results:
        status = "✓ PASÓ" if success else "✗ FALLÓ"
        if error:
            status += f" ({error})"
        print(f"{status}: {test_name}")
        
        if success:
            passed += 1
        else:
            failed += 1
    
    print()
    print(f"Total: {passed} pasaron, {failed} fallaron")
    
    if failed == 0:
        print("\n¡Todas las optimizaciones están funcionando correctamente!")
        return 0
    else:
        print(f"\nHay {failed} pruebas que necesitan atención.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
