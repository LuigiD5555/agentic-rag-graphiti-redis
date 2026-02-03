#!/usr/bin/env python3
"""
Script para limpiar código bloat/residuo identificado por el análisis de coverage.
Elimina archivos huérfanos de manera controlada con opciones de dry-run y backup.
"""

import json
import os
import shutil
import argparse
from pathlib import Path
from typing import List, Dict, Set

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_ORPHANED_JSON = SCRIPT_DIR / "coverage_reports" / "orphaned_code.json"

def load_orphaned_files(orphaned_json_path: str) -> Dict[str, List[str]]:
    """Carga el archivo JSON con archivos huérfanos."""
    with open(orphaned_json_path, 'r') as f:
        data = json.load(f)
    return data

def analyze_files_by_category(orphaned_files: List[str]) -> Dict[str, List[str]]:
    """Analiza y categoriza los archivos huérfanos."""
    categories = {
        'loaders': [],
        'memory': [],
        'query': [],
        'ingestion': [],
        'pipeline': [],
        'discovery': [],
        'checkpoint': [],
        'strategies': [],
        'metrics': [],
        'llm_backends': [],
        'storage_backends': [],
        'api': [],
        'utils': [],
        'core': [],
        'other': []
    }
    
    for file_path in orphaned_files:
        rel_path = file_path.replace('/mnt/Documents/Documents/Programacion/Proyectos_Programacion/RAG Project/rag-agentic-graphiti/', '')
        
        # Categorizar
        if 'loaders' in rel_path:
            categories['loaders'].append(rel_path)
        elif 'memory' in rel_path:
            categories['memory'].append(rel_path)
        elif 'query' in rel_path and 'workflows/query' in rel_path:
            categories['query'].append(rel_path)
        elif 'pipeline' in rel_path:
            categories['pipeline'].append(rel_path)
        elif 'discovery' in rel_path:
            categories['discovery'].append(rel_path)
        elif 'checkpoint' in rel_path:
            categories['checkpoint'].append(rel_path)
        elif 'strategies' in rel_path:
            categories['strategies'].append(rel_path)
        elif 'metrics' in rel_path:
            categories['metrics'].append(rel_path)
        elif 'ingestion' in rel_path and 'workflows/ingestion' in rel_path:
            categories['ingestion'].append(rel_path)
        elif 'llm' in rel_path and 'backends' in rel_path:
            categories['llm_backends'].append(rel_path)
        elif 'storage' in rel_path and 'backends' in rel_path:
            categories['storage_backends'].append(rel_path)
        elif 'api' in rel_path:
            categories['api'].append(rel_path)
        elif 'utils' in rel_path:
            categories['utils'].append(rel_path)
        elif 'core' in rel_path:
            categories['core'].append(rel_path)
        else:
            categories['other'].append(rel_path)
    
    return categories

def create_backup(files: List[str], backup_dir: str) -> None:
    """Crea una copia de seguridad de los archivos a eliminar."""
    os.makedirs(backup_dir, exist_ok=True)
    
    for file_path in files:
        if os.path.exists(file_path):
            rel_path = file_path.replace('/mnt/Documents/Documents/Programacion/Proyectos_Programacion/RAG Project/rag-agentic-graphiti/', '')
            backup_path = os.path.join(backup_dir, rel_path)
            os.makedirs(os.path.dirname(backup_path), exist_ok=True)
            shutil.copy2(file_path, backup_path)
            print(f"  Backup creado: {backup_path}")

def delete_files(files: List[str], dry_run: bool = True) -> None:
    """Elimina archivos (o simula en dry-run)."""
    for file_path in files:
        if os.path.exists(file_path):
            if dry_run:
                print(f"  [DRY-RUN] Eliminaría: {file_path}")
            else:
                os.remove(file_path)
                print(f"  Eliminado: {file_path}")
                
                # Intentar eliminar directorio padre si está vacío
                parent_dir = os.path.dirname(file_path)
                try:
                    if not os.listdir(parent_dir):
                        os.rmdir(parent_dir)
                        print(f"  Directorio vacío eliminado: {parent_dir}")
                except (OSError, FileNotFoundError):
                    pass

def cleanup_by_category(categories: Dict[str, List[str]], 
                        selected_categories: List[str],
                        base_path: str,
                        dry_run: bool = True,
                        backup: bool = False) -> None:
    """Realiza la limpieza por categorías seleccionadas."""
    
    # Si no se especifican categorías, usar todas
    if not selected_categories:
        selected_categories = list(categories.keys())
    
    total_files = 0
    for category in selected_categories:
        if category in categories and categories[category]:
            files = categories[category]
            full_paths = [os.path.join(base_path, f) for f in files]
            
            print(f"\n=== {category.upper()} ===")
            print(f"Archivos a procesar: {len(files)}")
            
            if backup and not dry_run:
                backup_dir = os.path.join(base_path, f"backup_bloat_{category}")
                print(f"Creando backup en: {backup_dir}")
                create_backup(full_paths, backup_dir)
            
            delete_files(full_paths, dry_run)
            total_files += len(files)
    
    print(f"\n=== RESUMEN ===")
    print(f"Total archivos procesados: {total_files}")
    if dry_run:
        print("MODO DRY-RUN: No se eliminó ningún archivo")
        print("Use --execute para realizar la limpieza real")

def main():
    parser = argparse.ArgumentParser(description='Limpia código bloat identificado por coverage analysis')
    parser.add_argument(
        '--orphaned-json',
        default=str(DEFAULT_ORPHANED_JSON),
        help='Ruta al archivo JSON con archivos huérfanos')
    parser.add_argument('--base-path', default='.',
                       help='Ruta base del proyecto')
    parser.add_argument('--categories', nargs='+',
                       choices=['loaders', 'memory', 'query', 'ingestion', 'pipeline', 
                                'discovery', 'checkpoint', 'strategies', 'metrics',
                                'llm_backends', 'storage_backends', 'api', 'utils', 
                                'core', 'other', 'all'],
                       help='Categorías a limpiar (default: todas)')
    parser.add_argument('--execute', action='store_false', dest='dry_run',
                       help='Ejecutar la limpieza real (sin dry-run)')
    parser.add_argument('--backup', action='store_true',
                       help='Crear backup antes de eliminar')
    parser.add_argument('--list-categories', action='store_true',
                       help='Listar categorías disponibles y salir')
    
    args = parser.parse_args()
    
    # Cargar archivos huérfanos
    data = load_orphaned_files(args.orphaned_json)
    orphaned_files = data['orphaned_files']
    
    print(f"=== LIMPIEZA DE CÓDIGO BLOAT ===")
    print(f"Archivos huérfanos totales: {len(orphaned_files)}")
    print(f"Líneas huérfanas: {data.get('total_orphaned_lines', 'N/A')}")
    
    # Categorizar archivos
    categories = analyze_files_by_category(orphaned_files)
    
    if args.list_categories:
        print("\n=== CATEGORÍAS DISPONIBLES ===")
        for category, files in categories.items():
            if files:
                print(f"{category}: {len(files)} archivos")
                for f in files[:2]:
                    print(f"  - {f}")
                if len(files) > 2:
                    print(f"    ... y {len(files) - 2} más")
        return
    
    # Si se especifica 'all', incluir todas las categorías
    if args.categories and 'all' in args.categories:
        args.categories = [c for c in categories.keys() if categories[c]]
    
    # Realizar limpieza
    cleanup_by_category(
        categories=categories,
        selected_categories=args.categories,
        base_path=args.base_path,
        dry_run=args.dry_run,
        backup=args.backup
    )

if __name__ == '__main__':
    main()
