#!/usr/bin/env bash
set -o errexit

# 1️⃣ Install dependencies
pip install -r requirements.txt

# 2️⃣ Run migrations
python manage.py migrate

# 3️⃣ Collect static files
python manage.py collectstatic --noinput

# 4️⃣ Create superuser from environment variables (if not exists)
if [ -z "$ADMIN_USER" ] || [ -z "$ADMIN_EMAIL" ] || [ -z "$ADMIN_PASS" ]; then
  echo "WARNING: ADMIN_USER, ADMIN_EMAIL, or ADMIN_PASS not set. Skipping superuser creation."
else
  echo "from django.contrib.auth import get_user_model; User = get_user_model(); \
if not User.objects.filter(username='$ADMIN_USER').exists(): \
    User.objects.create_superuser('$ADMIN_USER','$ADMIN_EMAIL','$ADMIN_PASS')" | python manage.py shell
  echo "✅ Superuser checked/created"
fi
