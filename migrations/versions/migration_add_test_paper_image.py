"""Add test_paper_image table for AI pipeline integration

Revision ID: a3f88c1d9e02
Revises: d11110673a42
Create Date: 2026-01-01 00:00:00.000000

HOW TO RUN:
    flask db upgrade

HOW TO ROLLBACK:
    flask db downgrade a3f88c1d9e02~1
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a3f88c1d9e02'
down_revision = 'bafccec07302'   # ← your existing latest migration ID
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'test_paper_image',

        # ── Primary Key ───────────────────────────────────────────────────────
        sa.Column('id', sa.Integer(), nullable=False),

        # ── Foreign Keys ──────────────────────────────────────────────────────
        sa.Column('test_id',              sa.Integer(), nullable=False),
        sa.Column('student_id',           sa.Integer(), nullable=True),   # null until assigned
        sa.Column('suggested_student_id', sa.Integer(), nullable=True),   # fuzzy-match suggestion
        sa.Column('uploaded_by',          sa.Integer(), nullable=False),  # teacher

        # ── File Storage ──────────────────────────────────────────────────────
        sa.Column('image_path',        sa.String(length=500), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),

        # ── Pipeline / OCR Output ─────────────────────────────────────────────
        sa.Column('ocr_name',     sa.String(length=300), nullable=True),
        sa.Column('ocr_score',    sa.String(length=50),  nullable=True),
        sa.Column('ocr_label',    sa.String(length=500), nullable=True),
        sa.Column('ocr_raw_json', sa.Text(),             nullable=True),

        # ── Matching / Assignment ─────────────────────────────────────────────
        # 0.0–100.0 fuzzy match score; NULL means OCR name was unusable
        sa.Column('match_confidence', sa.Float(), nullable=True),

        # ── Status ────────────────────────────────────────────────────────────
        # Values: 'pending' | 'uncertain' | 'assigned' | 'error'
        sa.Column('status', sa.String(length=20), nullable=False,
                  server_default='pending'),

        sa.Column('error_message', sa.Text(), nullable=True),

        # ── Timestamps ────────────────────────────────────────────────────────
        sa.Column('uploaded_at',  sa.DateTime(), nullable=True),
        sa.Column('assigned_at',  sa.DateTime(), nullable=True),
        sa.Column('processed_at', sa.DateTime(), nullable=True),

        # ── Constraints ───────────────────────────────────────────────────────
        sa.ForeignKeyConstraint(['test_id'],              ['test.id'],    ),
        sa.ForeignKeyConstraint(['student_id'],           ['student.id'], ),
        sa.ForeignKeyConstraint(['suggested_student_id'], ['student.id'], ),
        sa.ForeignKeyConstraint(['uploaded_by'],          ['teacher.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    # Speed up the most common queries:
    #   • "All images for test X"          (teacher review screen)
    #   • "All assigned images for test X" (count pending)
    #   • "All images for student Y"       (student grades page)

    with op.batch_alter_table('test_paper_image', schema=None) as batch_op:
        batch_op.create_index(
            'ix_test_paper_image_test_id',
            ['test_id'],
            unique=False
        )
        batch_op.create_index(
            'ix_test_paper_image_student_id',
            ['student_id'],
            unique=False
        )
        batch_op.create_index(
            'ix_test_paper_image_status',
            ['status'],
            unique=False
        )
        # Composite: teacher review page queries test + status together constantly
        batch_op.create_index(
            'ix_test_paper_image_test_status',
            ['test_id', 'status'],
            unique=False
        )


def downgrade():
    with op.batch_alter_table('test_paper_image', schema=None) as batch_op:
        batch_op.drop_index('ix_test_paper_image_test_status')
        batch_op.drop_index('ix_test_paper_image_status')
        batch_op.drop_index('ix_test_paper_image_student_id')
        batch_op.drop_index('ix_test_paper_image_test_id')

    op.drop_table('test_paper_image')