"""Add term_tag and component_tag to test table (Method 2 - Activity-Based Grading)

Revision ID: b7e21f3c8d04
Revises: a3f88c1d9e02
Create Date: 2026-01-01 00:00:00.000000

HOW TO RUN:
    flask db upgrade

HOW TO ROLLBACK:
    flask db downgrade b7e21f3c8d04~1

WHAT THIS DOES:
    Adds two nullable columns to the 'test' table:
      - term_tag:      which grading period this test belongs to
                       e.g. "Prelims", "Midterms", "Finals"
      - component_tag: which formula component this test scores fall under
                       e.g. "Quizzes", "Exams", "Projects"

    Both are nullable so existing test rows are not broken.
    Old tests (no tags) will be ignored by the new formula engine
    and can be cleaned up manually or left in place.
"""
from alembic import op
import sqlalchemy as sa


revision = 'b7e21f3c8d04'
down_revision = 'a3f88c1d9e02'   # ← your previous latest migration
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('test', schema=None) as batch_op:
        batch_op.add_column(sa.Column('raw_score', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('max_score', sa.Float(), nullable=True))
        batch_op.add_column(
            sa.Column('term_tag', sa.String(length=50), nullable=True)
        )
        batch_op.add_column(
            sa.Column('component_tag', sa.String(length=100), nullable=True)
        )
        # Index on term_tag alone (frequent filter: "all Prelim tests for class X")
        batch_op.create_index(
            'ix_test_term_tag',
            ['term_tag'],
            unique=False
        )
        # Composite index (most common query pattern in formula engine:
        # "all tests for class X where term=Prelims and component=Quizzes")
        batch_op.create_index(
            'ix_test_class_term_component',
            ['class_id', 'term_tag', 'component_tag'],
            unique=False
        )


def downgrade():
    with op.batch_alter_table('test', schema=None) as batch_op:
        batch_op.drop_column('max_score')
        batch_op.drop_column('raw_score')
        batch_op.drop_index('ix_test_class_term_component')
        batch_op.drop_index('ix_test_term_tag')
        batch_op.drop_column('component_tag')
        batch_op.drop_column('term_tag')