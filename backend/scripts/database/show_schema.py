#!/usr/bin/env python3
"""
Display the assistant database schema.
Shows all tables and their columns with types.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.database import sync_engine
from sqlalchemy import inspect, text

def show_schema():
    """Display all tables and their schemas"""
    inspector = inspect(sync_engine)
    
    # Get all table names
    tables = inspector.get_table_names()
    
    if not tables:
        print("No tables found in database")
        return
    
    print("="*60)
    print("DATABASE SCHEMA")
    print("="*60)
    
    for table_name in tables:
        print(f"\nTable: {table_name}")
        print("-"*40)
        
        # Get columns for this table
        columns = inspector.get_columns(table_name)
        for col in columns:
            col_type = str(col['type'])
            nullable = "NULL" if col['nullable'] else "NOT NULL"
            default = f"DEFAULT {col['default']}" if col.get('default') else ""
            print(f"  {col['name']:<30} {col_type:<20} {nullable:<10} {default}")
        
        # Get primary keys
        pk = inspector.get_pk_constraint(table_name)
        if pk['constrained_columns']:
            print(f"  PRIMARY KEY: {', '.join(pk['constrained_columns'])}")
        
        # Get foreign keys
        fks = inspector.get_foreign_keys(table_name)
        for fk in fks:
            print(f"  FOREIGN KEY: {', '.join(fk['constrained_columns'])} -> {fk['referred_table']}.{', '.join(fk['referred_columns'])}")
        
        # Get indexes
        indexes = inspector.get_indexes(table_name)
        for idx in indexes:
            if not idx.get('unique'):
                print(f"  INDEX: {idx['name']} on ({', '.join(idx['column_names'])})")
            else:
                print(f"  UNIQUE INDEX: {idx['name']} on ({', '.join(idx['column_names'])})")

def show_row_counts():
    """Show Postgres planner-estimated row counts for all user tables."""
    print("\n" + "="*60)
    print("ESTIMATED ROW COUNTS")
    print("="*60)
    
    with sync_engine.connect() as conn:
        # PostgreSQL-optimized table scan: use catalog stats instead of COUNT(*) per table.
        result = conn.execute(text("""
            SELECT
                c.relname AS table_name,
                GREATEST(c.reltuples, 0)::BIGINT AS estimated_rows
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'p')
              AND n.nspname = 'public'
            ORDER BY c.relname
        """))

        for table_name, estimated_rows in result:
            print(f"  {table_name:<30} {int(estimated_rows):>10} rows (estimated)")

if __name__ == "__main__":
    try:
        show_schema()
        show_row_counts()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
