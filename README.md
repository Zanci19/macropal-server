# macropal-server

MacroPal's own API: Firebase Auth for identity, PostgreSQL for everything else.

```
Expo app
   │
   ├── Firebase Authentication        email/password, Google, Apple later
   │
   └── MacroPal API                   Nginx (HTTPS) -> FastAPI (127.0.0.1:8000)
          │
          ├── verifies the Firebase ID token
          │
          └── PostgreSQL
                 ├── users            foods            diary_entries
                 ├── meals            meal_items       weights
                 └── goals            favorites        custom_foods
                            ^
                 OpenFoodFacts dump / USDA (importers)
```

Firebase stores only the identity (uid, email, display name). Every piece of
MacroPal's own data lives in PostgreSQL, keyed on an internal `users.id` that is
linked to Firebase by `users.firebase_uid`. Nothing references Firebase
directly, so the app can move off it later without touching the data model.

The app does not talk to OpenFoodFacts at runtime either. Data is imported into
PostgreSQL and served from here, so search is fast and stays up when OFF is down.

---

## Layout

```
macropal-server/
├── app/
│   ├── config.py      pydantic-settings, reads .env / systemd environment
│   ├── database.py    engine, SessionLocal, Base, get_db
│   ├── auth.py        Firebase ID token verification -> User
│   ├── enums.py       sex, activity level, goal, unit system, meal keys
│   ├── models.py      Food (49 columns), FoodNutrient and the user tables
│   ├── schemas.py     request and response models
│   ├── nutrition.py   per-100g scaling and macro totals
│   ├── services.py    food-reference resolution and response building
│   ├── search.py      full-text + trigram search query building
│   ├── main.py        app, CORS, /health
│   └── routers/       foods, users, diary, meals, custom_foods, weights, favorites
├── alembic/           migrations (0001 foods, 0002 staging, 0003 user tables)
├── deploy/            macropal.service, nginx-macropal.conf
├── scripts/           seed_sample_foods.py
├── requirements.txt
└── .env.example
```

The code carries no comments by request; design decisions that are not obvious
from the code are recorded in this README instead. Two that matter:

- `SEARCH_VECTOR_SQL` in `app/models.py` and the identical string in
  `alembic/versions/0001_initial_schema.py` must be changed together.
- `alembic/env.py` imports `app.models` to register the tables on the metadata,
  and reads `models.Base.metadata` so the import is genuinely used.

---

## Server setup (Debian)

Steps 1–3 are the system; 4 onward is this repo.

### 1. Packages

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl wget unzip python3 python3-pip python3-venv \
    postgresql postgresql-client nginx
sudo systemctl enable --now postgresql
```

### 2. Database and role

```bash
sudo -u postgres psql
```

```sql
CREATE USER macropal WITH PASSWORD 'STRONG_PASSWORD_HERE';
CREATE DATABASE macropal OWNER macropal;
\q
```

### 3. The pg_trgm extension (do this as postgres, not as macropal)

Fuzzy search needs `pg_trgm`, and creating an extension requires superuser.
The `macropal` role is not one, so create it now:

```bash
sudo -u postgres psql -d macropal -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

The migration also runs `CREATE EXTENSION IF NOT EXISTS pg_trgm`, which is a
harmless no-op once it exists. Skip this step and `alembic upgrade` fails with
`permission denied to create extension`.

### 4. Clone

`/opt` is not writable by your user, hence the `sudo git clone` + `chown`:

```bash
cd /opt
sudo git clone https://github.com/Zanci19/macropal-server.git
sudo chown -R macropal:macropal /opt/macropal-server
cd /opt/macropal-server
```

### 5. Virtualenv and dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 6. Configure

```bash
cp .env.example .env
nano .env          # set the real DATABASE_URL password
chmod 600 .env
```

`.env` is read both by pydantic-settings (when you run uvicorn by hand) and by
systemd via `EnvironmentFile`. systemd parses it literally: no quotes, no `$VAR`
expansion, no trailing comments.

### 7. Create the tables

```bash
alembic upgrade head
```

Verify:

```bash
psql -h localhost -U macropal -d macropal -c "\d foods"
psql -h localhost -U macropal -d macropal -c "\di foods*"
```

You should see the `foods` and `food_nutrients` tables, and five indexes on
`foods` including `ix_foods_search_vector` (GIN) and `ix_foods_name_trgm` (GIN).

### 8. Seed a couple of rows and run it

```bash
python -m scripts.seed_sample_foods
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Then from your laptop:

```bash
curl http://SERVER_IP:8000/health
curl "http://SERVER_IP:8000/v1/foods/search?q=chocolate"
curl http://SERVER_IP:8000/v1/foods/barcode/123456789
```

`http://SERVER_IP:8000/docs` gives you Swagger.

Stop it with Ctrl-C — step 9 is what actually keeps it running.

### 9. systemd

The unit file assumes the Linux user is `macropal` and the checkout is
`/opt/macropal-server`; edit `deploy/macropal.service` if either differs.

```bash
sudo cp deploy/macropal.service /etc/systemd/system/macropal.service
sudo systemctl daemon-reload
sudo systemctl enable --now macropal
systemctl status macropal
journalctl -u macropal -f
```

It binds `127.0.0.1:8000` only — Nginx is the way in.

### 10. Nginx

```bash
sudo cp deploy/nginx-macropal.conf /etc/nginx/sites-available/macropal
sudo nano /etc/nginx/sites-available/macropal     # set your real server_name
sudo ln -s /etc/nginx/sites-available/macropal /etc/nginx/sites-enabled/macropal
sudo nginx -t
sudo systemctl reload nginx
```

### 11. Firewall

Allow SSH *before* enabling, or you lock yourself out:

```bash
sudo apt install -y ufw
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

Port 5432 stays closed. FastAPI reaches PostgreSQL over localhost.

### 12. HTTPS

Once DNS points at the box:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d api.yourdomain.com
```

The Expo app then uses `https://api.yourdomain.com` instead of an IP.

### Deploying a change

```bash
cd /opt/macropal-server
git pull
source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
sudo systemctl restart macropal
```

---

## Authentication

The food endpoints are public. Everything under `/v1/me` and `/v1/diary`
requires a Firebase ID token:

```
Authorization: Bearer <firebase id token>
```

The app signs in with the Firebase SDK, calls `getIdToken()`, and sends that.
The server verifies the signature with the Firebase Admin SDK, reads the `uid`,
and looks up `users.firebase_uid`. A uid with no row yet gets one created on its
first request, so there is no separate registration call — the Expo app's
profile-setup screen just PATCHes `/v1/me`.

To make this work the server needs a **service account key**, which is not the
same file as the app's `google-services.json`. In the Firebase console: Project
settings -> Service accounts -> Generate new private key. Put it on the server
outside the repo, for example:

```bash
sudo install -o macropal -g macropal -m 600 firebase-service-account.json \
    /opt/macropal-server/firebase-service-account.json
```

and point `.env` at it:

```
FIREBASE_CREDENTIALS_FILE=/opt/macropal-server/firebase-service-account.json
```

That file is a credential. Keep it mode 600, never commit it, and rotate it if
it leaks. If it is missing or unreadable, authenticated requests answer
`503 Authentication is not configured on this server` rather than a vague 500.

`FIREBASE_CHECK_REVOKED=true` additionally rejects tokens from sessions that
were signed out or disabled. It costs a Firebase lookup per request, so it is
off by default; turn it on if you add account bans or remote sign-out.

## API

| Method | Path                        | Auth | Purpose                        |
| ------ | --------------------------- | ---- | ------------------------------ |
| GET    | `/`                         | —    | name / status / version        |
| GET    | `/health`                   | —    | `ok` or `degraded` + DB check  |
| GET    | `/docs`                     | —    | Swagger UI                     |
| GET    | `/v1/foods/search`          | —    | search                         |
| GET    | `/v1/foods/barcode/{code}`  | —    | barcode lookup (full detail)   |
| GET    | `/v1/foods/{id}`            | —    | one food by id (full detail)   |
| GET    | `/v1/me`                    | yes  | current profile                |
| PATCH  | `/v1/me`                    | yes  | update profile and targets     |
| GET    | `/v1/me/goals`              | yes  | target history                 |
| POST   | `/v1/me/goals`              | yes  | set targets from a date        |
| GET    | `/v1/diary/day/{date}`      | yes  | a day, split by meal, + totals |
| GET    | `/v1/diary/summary`         | yes  | daily totals over a range      |
| POST   | `/v1/diary/entries`         | yes  | log a food                     |
| PATCH  | `/v1/diary/entries/{id}`    | yes  | edit an entry                  |
| DELETE | `/v1/diary/entries/{id}`    | yes  | delete an entry                |
| POST   | `/v1/diary/log-meal`        | yes  | log every item of a saved meal |
| GET    | `/v1/me/meals`              | yes  | saved meals                    |
| POST   | `/v1/me/meals`              | yes  | create a saved meal            |
| GET    | `/v1/me/meals/{id}`         | yes  | one saved meal                 |
| PATCH  | `/v1/me/meals/{id}`         | yes  | rename or replace items        |
| DELETE | `/v1/me/meals/{id}`         | yes  | delete a saved meal            |
| GET    | `/v1/me/custom-foods`       | yes  | own foods, `?q=` filters       |
| POST   | `/v1/me/custom-foods`       | yes  | create own food                |
| GET    | `/v1/me/custom-foods/{id}`  | yes  | one own food                   |
| PATCH  | `/v1/me/custom-foods/{id}`  | yes  | update own food                |
| DELETE | `/v1/me/custom-foods/{id}`  | yes  | delete own food                |
| GET    | `/v1/me/weights`            | yes  | weight history                 |
| PUT    | `/v1/me/weights/{date}`     | yes  | record or replace a weigh-in   |
| DELETE | `/v1/me/weights/{date}`     | yes  | delete a weigh-in              |
| GET    | `/v1/me/favorites`          | yes  | favorites                      |
| POST   | `/v1/me/favorites`          | yes  | add a favorite                 |
| DELETE | `/v1/me/favorites/{id}`     | yes  | remove a favorite              |

Anything that points at a food — a diary entry, a meal item, a favorite — takes
exactly one of `food_id` (the shared database) or `custom_food_id` (your own
foods), enforced by both the request model and a database CHECK. Sending both,
or neither, is a 422.

### `GET /v1/foods/search`

| Param             | Default | Notes                                           |
| ----------------- | ------- | ----------------------------------------------- |
| `q`               | —       | required; text or a barcode                     |
| `page`            | 1       |                                                 |
| `page_size`       | 25      | capped at `MAX_PAGE_SIZE`                       |
| `country`         | —       | lowercase English name, e.g. `slovenia`         |
| `source`          | —       | `openfoodfacts` / `usda` / `macropal` / `user`  |
| `brand`           | —       | exact, case-insensitive                         |
| `include_obsolete`| false   |                                                 |

The response carries `strategy`, naming which of three paths answered:

- **`barcode`** — `q` was 8–14 digits and matched a row exactly.
- **`fulltext`** — GIN index on the generated `search_vector`. Every token
  becomes a prefix term, so `choco mil` matches `Chocolate Milk`.
- **`fuzzy`** — only when full-text found nothing: pg_trgm similarity on
  `lower(name)`, so `nutela` still returns Nutella. Tune with
  `FUZZY_THRESHOLD`.

`has_more` instead of a total count — counting full-text matches across a
multi-million-row dump costs as much as the search itself.

---

## Schema notes

`foods` holds the 49 columns we settled on, plus a generated `search_vector`.
A few decisions worth remembering:

- **`barcode` is indexed, not unique.** OFF, USDA and user submissions can all
  carry the same barcode. Row identity is `UNIQUE (source, source_id)`.
  Collapsing duplicates into one canonical food is a later deduplication step.
- **`search_vector` is a stored generated column** using the `simple`
  configuration — no stemming. The dump is multilingual, so any single language
  configuration would stem some rows right and mangle the rest. Postgres
  maintains it, so importers never write to it.
- **Nutrition is `NUMERIC`**, not float — exact on import, no drift. SQLAlchemy
  hands Python plain floats so JSON stays clean.
- **`countries` is `TEXT[]`** of lowercase English names without the OFF `en:`
  prefix (`{slovenia,austria}`), with a GIN index, so country filtering uses
  `@>` and stays indexed.
- **`raw_data` (JSONB) and `search_vector` are deferred** in the ORM. A full OFF
  product blob dwarfs the rest of the row and no endpoint returns it, so
  searches must not drag it along.
- **Micronutrients go in `food_nutrients`**, not in new columns — calcium, iron,
  vitamin B12, caffeine and whatever OFF adds next, keyed by
  `(food_id, nutrient_code)`. No `ALTER TABLE` when the taxonomy grows.

`updated_at` is maintained by SQLAlchemy's `onupdate`, which means it only moves
on ORM writes. Bulk `COPY`-based imports must set it themselves (or we add a
trigger when the importer lands).

### User tables

- **`users.firebase_uid` is the only link to Firebase.** Everything else
  references the internal `users.id`, so dropping Firebase later is a change to
  one table, not to the whole schema.
- **Custom foods are a separate table, not rows in `foods`.** One user's
  "my protein shake" must never surface in global search, and `foods` stays
  purely importer-owned.
- **`diary_entries.food_id` is `ON DELETE RESTRICT`**, so an importer cannot
  delete a shared food out from under somebody's logged day. `custom_food_id`
  is `ON DELETE CASCADE` — your own food, your own entries.
- **`goals` is the history, `users` holds the current values.** A POST to
  `/v1/me/goals` writes both in one transaction. The duplication is deliberate:
  reading today's targets must not need a window function over history.
- **Enum-ish columns are CHECK-constrained** and mirrored by Python enums in
  `app/enums.py`, so a bad value is a 422 from FastAPI rather than a stray
  string in the database. `meal` is restricted to the app's four meal keys.
- **Macros are computed, never stored.** `app/nutrition.py` scales per-100g
  values by `quantity_g` on read, so correcting a food's nutrition fixes every
  past diary entry instead of leaving stale totals behind.

---

## Not built yet

- `importers/openfoodfacts.py` — download dump, decompress, parse, normalize
  nutrients, `COPY` into a staging table, validate, merge into `foods`.
  Deliberately not `session.add()` per product: the dump is millions of rows.
- `importers/usda.py` — maps `fdc_id` -> `source_id`, `gtin_upc` -> `barcode`,
  `brand_owner`, `branded_food_category` -> `category`.
- Deduplication across sources into one canonical food.
- Recipes, friends/social, subscription status, admin and moderation.
- Images in object storage rather than hotlinked source URLs.

## Migrating the app off Firestore

The data model is in place; the Expo app is what still has to move.

1. **Now** — Firebase Auth plus Firestore, as today.
2. **Next** — Firebase Auth, with the app reading foods and writing the diary
   through this API while Firestore stays as a fallback. Backfill each user's
   existing Firestore diary and profile into PostgreSQL on first sign-in.
3. **Target** — Firebase Auth plus this API only, Firestore removed.

One thing to plan for in step 3: Firestore gave the app offline reads and
writes for free. An HTTP API does not, so the app needs its own local cache and
a write queue for entries logged without a signal.
