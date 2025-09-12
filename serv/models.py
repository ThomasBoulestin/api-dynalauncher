from flask_sqlalchemy import SQLAlchemy
from flask import Flask

db = SQLAlchemy()


class SqlJob(db.Model):
    """Standard SQL Alchemy Job object
    """
    id = db.Column(db.Integer, primary_key=True)
    input = db.Column(db.String(300), unique=False, nullable=True)
    solver = db.Column(db.String(300), unique=False, nullable=True)
    command = db.Column(db.String(300), unique=False, nullable=True)
    ncpu = db.Column(db.Integer, unique=False, nullable=True)
    memory = db.Column(db.String(300), unique=False, nullable=True)
    status = db.Column(db.String(300), unique=False, nullable=True)
    progress = db.Column(db.String(300), unique=False, nullable=True)
    started = db.Column(db.Integer, unique=False, nullable=True)
    ETA = db.Column(db.Integer, unique=False, nullable=True)
    elapsed = db.Column(db.Integer, unique=False, nullable=True)
    current = db.Column(db.Float, unique=False, nullable=True)
    end = db.Column(db.Float, unique=False, nullable=True)
    pid = db.Column(db.Integer, unique=False, nullable=True)
    expr = db.Column(db.String(300), unique=False, nullable=True)
    a_mass = db.Column(db.Float, unique=False, nullable=True)
    pct_mass = db.Column(db.Float, unique=False, nullable=True)
    sender = db.Column(db.String(300), unique=False, nullable=True)

    def __repr__(self):
        return f"<SqlJob {self.id}>"


def init_db() -> None:
    """Run this script to initialize a brand new db !
    """
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///DynaLauncher.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)

    with app.app_context():
        db.create_all()


def ensure_schema() -> None:
    """Ensure DB schema is up-to-date for existing databases.

    - Adds missing columns that were introduced after initial table creation.
    Currently handled: `sender` column on `SqlJob`.
    """
    # Accessing db.engine requires an app context; caller must ensure it.
    from sqlalchemy import text

    table_name = SqlJob.__table__.name

    # Use a transaction-safe connection for DDL
    with db.engine.begin() as conn:
        # Get existing columns via PRAGMA for SQLite
        pragma = conn.execute(text(f'PRAGMA table_info("{table_name}")'))
        existing_cols = {row[1] for row in pragma.fetchall()}

        if "sender" not in existing_cols:
            # Add the new column as nullable VARCHAR(300)
            conn.execute(
                text(f'ALTER TABLE "{table_name}" ADD COLUMN sender VARCHAR(300)'))


if __name__ == "__main__":
    init_db()
