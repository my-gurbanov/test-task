import typing

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}


revision: typing.Final = ${repr(up_revision)}
down_revision: typing.Final = ${repr(down_revision)}
branch_labels: typing.Final = ${repr(branch_labels)}
depends_on: typing.Final = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
