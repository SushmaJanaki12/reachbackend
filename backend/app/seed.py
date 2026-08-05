from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from .database import SessionLocal, engine
from .models import Permission, Role, User, SmsTemplate
from .security import hash_password
from .config import settings

BACKEND_DIR = Path(__file__).resolve().parent.parent
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"

# (code, module, label)
PERMISSIONS = [
    ("project.view", "Projects", "View projects"),
    ("project.create", "Projects", "Create projects"),
    ("project.edit", "Projects", "Edit projects"),
    ("project.archive", "Projects", "Archive projects"),
    ("project.delete", "Projects", "Delete projects"),
    ("project.configure_channels", "Projects", "Configure channels"),
    ("project.manage_members", "Projects", "Manage project members"),
    ("campaign.view", "Campaigns", "View campaigns"),
    ("campaign.create", "Campaigns", "Create campaigns"),
    ("campaign.edit", "Campaigns", "Edit campaigns"),
    ("campaign.delete", "Campaigns", "Delete campaigns"),
    ("dataset.upload", "Datasets", "Upload datasets"),
    ("dataset.override_warnings", "Datasets", "Force-import rows with unresolved validation warnings"),
    ("content.edit", "Content", "Edit content"),
    ("campaign.send", "Sending", "Send campaigns"),
    ("template.view", "Templates", "View message templates"),
    ("template.edit", "Templates", "Create and edit message templates"),
    ("template.archive", "Templates", "Archive message templates"),
    ("template.delete", "Templates", "Delete message templates"),
    ("tracking.view_all", "Tracking", "View all tracking"),
    ("tracking.view_own", "Tracking", "View own tracking"),
    ("report.export", "Reports", "Export reports"),
    ("suppression.manage", "Suppressions", "Manage the unsubscribe/suppression list"),
    ("user.manage", "Users", "Manage users"),
    ("role.manage", "Roles", "Manage roles & permissions"),
    ("system.configure", "System", "System configuration"),
]

USER_ROLE_PERMS = {
    "project.view", "campaign.view", "campaign.create", "campaign.edit",
    "dataset.upload", "content.edit", "campaign.send",
    "tracking.view_own", "report.export",
    "template.view", "template.edit",
}


def _migrate():
    """Apply schema via Alembic. All future schema changes belong in a new
    revision under migrations/versions/ (alembic revision --autogenerate -m "..."),
    not edits here."""
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    existing_tables = set(inspect(engine).get_table_names())
    if "alembic_version" not in existing_tables and "projects" in existing_tables:
        # DB already has the pre-Alembic schema (from the old create_all()+manual
        # ALTER TABLE flow) -- record it as up to date instead of re-running the
        # initial migration's CREATE TABLE statements against existing tables.
        command.stamp(cfg, "head")
    else:
        command.upgrade(cfg, "head")


def seed():
    _migrate()
    db: Session = SessionLocal()
    try:
        # permissions
        by_code = {p.code: p for p in db.query(Permission).all()}
        for code, module, label in PERMISSIONS:
            if code not in by_code:
                p = Permission(code=code, module=module, label=label)
                db.add(p)
                by_code[code] = p
        db.commit()
        by_code = {p.code: p for p in db.query(Permission).all()}

        # admin role (all permissions)
        admin_role = db.query(Role).filter_by(name="Admin").first()
        if not admin_role:
            admin_role = Role(name="Admin", description="Full platform control", is_system=True)
            db.add(admin_role)
        admin_role.permissions = list(by_code.values())

        # user role (scoped set)
        user_role = db.query(Role).filter_by(name="User").first()
        if not user_role:
            user_role = Role(name="User", description="Operational role scoped to assigned projects", is_system=True)
            db.add(user_role)
        user_role.permissions = [by_code[c] for c in USER_ROLE_PERMS if c in by_code]
        db.commit()

        # admin user (opt-in: local dev/demo only, never in production)
        admin_seeded = False
        if settings.seed_default_admin:
            admin = db.query(User).filter_by(email="admin@reach.io").first()
            if not admin:
                admin = User(
                    name="Reach Admin", email="admin@reach.io",
                    hashed_password=hash_password("Admin@123"),
                    is_active=True, role_id=admin_role.id,
                )
                db.add(admin)
                admin_seeded = True

        # sample user
        member = db.query(User).filter_by(email="user@reach.io").first()
        if not member:
            member = User(
                name="Sample User", email="user@reach.io",
                hashed_password=hash_password("User@123"),
                is_active=True, role_id=user_role.id,
            )
            db.add(member)
        db.commit()

        # sample DLT SMS template (matches the configured sender/template if present)
        if db.query(SmsTemplate).count() == 0:
            db.add(SmsTemplate(
                name="MISTA EATS — OTP",
                template_id=settings.sms_template_id or "1707168726031344535",
                sender_id=settings.sms_from or "MISTAE",
                body=("Dear customer, use this One Time Password {#var#} to verify your "
                      "MISTA EATS account. This OTP will be valid for the next 10 mins."),
                is_active=True,
            ))
            db.commit()

        if admin_seeded:
            print("Seed complete. Default admin created: admin@reach.io / Admin@123 "
                  "-- rotate this password immediately.  |  User: user@reach.io / User@123")
        else:
            print("Seed complete. User: user@reach.io / User@123  "
                  "(set SEED_DEFAULT_ADMIN=true to also create the default admin account)")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
