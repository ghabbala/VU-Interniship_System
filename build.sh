#!/usr/bin/env bash
set -o errexit

# 1️⃣ Install dependencies
pip install -r requirements.txt

# 2️⃣ Run migrations
python manage.py migrate

# 3️⃣ Collect static files
python manage.py collectstatic --noinput

# 4️⃣ Create superuser from environment variables (if not exists)
# For your custom User model, use EMAIL as identifier.
if [ -z "$ADMIN_EMAIL" ] || [ -z "$ADMIN_PASS" ]; then
  echo "WARNING: ADMIN_EMAIL or ADMIN_PASS not set. Skipping superuser creation."
else
  python manage.py shell <<'PY'
import os
from django.contrib.auth import get_user_model

User = get_user_model()

email = os.environ.get("ADMIN_EMAIL")
password = os.environ.get("ADMIN_PASS")
first_name = os.environ.get("ADMIN_FIRST_NAME", "Admin")
last_name = os.environ.get("ADMIN_LAST_NAME", "User")

if not User.objects.filter(email=email).exists():
    User.objects.create_superuser(
        email=email,
        password=password,
        first_name=first_name,
        last_name=last_name,
    )
    print("✅ Superuser created:", email)
else:
    print("ℹ️ Superuser already exists:", email)
PY
fi
