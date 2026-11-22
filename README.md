# Cookit Backend

FastAPI backend for **Cookit** — a recipe book that also decides what's for
dinner. Ingredients on a shelf, dishes made of them, and a wheel that picks one.

Local username/password authentication is the primary sign-in. Authentik is an
optional additional method that users link to an existing account from the
frontend profile.

## What's in here

| Thing | Where |
|---|---|
| Schema, with the reasoning | [`app/db/models.py`](app/db/models.py) |
| Enumerated values | [`app/enums.py`](app/enums.py) |
| `@ingredient` mentions inside a step | [`app/services/mention_service.py`](app/services/mention_service.py) |
| The wheel and its weighting | [`app/services/randomizer_service.py`](app/services/randomizer_service.py) |
| Filtering ("uses any" / "I can cook it") | [`app/services/dish_service.py`](app/services/dish_service.py) |
| Markdown export | [`app/services/export_service.py`](app/services/export_service.py) |
| PDF export | [`app/services/pdf_service.py`](app/services/pdf_service.py) |
| Starter ingredient catalogue | [`app/data/catalogue.py`](app/data/catalogue.py) |

## Running it

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL="sqlite:///$(pwd)/cookit_dev.db"
export SECRET_KEY="$(openssl rand -hex 32)"
export PORT=8020
python main.py
```

Then fill it with something to look at:

```bash
python scripts/dev_seed.py --base-url http://localhost:8020 \
  --backdate "$(pwd)/cookit_dev.db"
```

That leaves two accounts — `saket` and `nadia`, password `cookit` — with a shelf
of sixty ingredients, twelve dishes with real recipes and `@`-mentions,
pairings, and six weeks of cook history, which is what the wheel's weighting
needs in order to do anything interesting. `--backdate` is local-SQLite-only and
is the one thing in the repo that writes to the database directly: the API has
no way to say "I cooked this three weeks ago", because the real app never needs
one.

Interactive API docs at `http://localhost:8020/docs`.

The app runs `alembic upgrade head` itself on startup, so a deploy that adds a
migration applies it with no separate step. `USE_ALEMBIC_MIGRATIONS=false` falls
back to `create_all()`, which builds the current schema but records no revision.

## The data model, briefly

A **dish** is made of **ingredients** (`dish_ingredients`, with amounts) and a
**recipe** (`recipe_steps`, one row per instruction). Both are real tables
rather than a blob of markdown, and that is the decision everything else rests
on:

* One step per row is what lets a step be handed over on its own — read aloud,
  sent to a chat, ticked off in cook mode.
* Ingredients as rows is what makes "what can I make with these?" a query
  instead of a text search — see [Filtering](#filtering) below, which is that
  question asked literally.

**Meal types** (breakfast / lunch / dinner / supper) are a row per value in
`dish_meal_types`, because the whole point is filtering and that wants an index.

**"Often had with"** is `dish_pairings`, stored as one canonically-sorted pair
(`dish_a_id < dish_b_id`, enforced by a CHECK) rather than two rows. Pairing is
mutual — if rice goes with dal then dal goes with rice — and storing it once
means it cannot end up half-recorded.

Everything belongs to one user. There is no sharing model, so every query
filters on `user_id` and two people can both own "onion" without colliding.

## `@`-mentions

A step's text is prose with typed references in it:

```
Fry the @[cumin seeds](8f1c…) until they pop, then add @[onion](2a4e…).
```

The markup is written by the editor's autocomplete and carries the ingredient's
UUID, not just its name — so "oil" and "olive oil" stay distinct and renaming an
ingredient later leaves every step still correct.

Two things happen on every step write:

1. `recipe_step_ingredients` is rebuilt from the mentions, so each step knows
   what it needs.
2. Anything mentioned is **added to the dish's ingredient list** if it wasn't
   there. This is the point of typing `@` mid-sentence: writing the recipe is
   what builds the shopping list, rather than two lists to keep in agreement.

Nothing is ever removed by the parser. Deleting a mention does not un-shop the
ingredient, because a dish routinely needs something no step spells out — salt,
the oil it's fried in — and silently dropping those would be worse than an
occasional stale row.

## Filtering

`GET /api/dishes` takes `?ingredient=<uuid>` repeated, plus `match`. The two
values ask genuinely different questions:

```
match=any   which dishes use any of these?        browsing
match=all   which of these can I cook right now?  the fridge
```

`any` is a test on the ingredients you named: the dish uses at least one.

`all` is a test on the **dish**: it matches when nothing the dish needs is
missing. Staples are treated as always in the house and ingredients marked
optional are never required, so ticking onion and tomato finds the dish wanting
onion, tomato and salt, and rejects the one that also wants paneer. That is what
"I have onion and tomato" actually means — a statement about what is interesting
in the fridge, not a claim to have run out of salt.

A dish that uses none of what you ticked is excluded from `all` even if it needs
nothing, because otherwise every dish with an empty ingredient list would match
every fridge and bury the real answers.

An ingredient UUID that resolves to nothing — a filter chip left over from an
ingredient since deleted — matches no dish. It is **not** the same as no filter,
and treating it as one is what used to widen the results to the whole book.

The wheel spins over this exact query, so the two can never disagree about what
matches.

## The wheel

`POST /api/randomizer/spin`. A bare POST means "anything". Everything else
narrows the pool: meal type, ingredients (see [Filtering](#filtering)), a time
limit, favourites, difficulty.

It is deliberately not `random.choice`. Weight rises with how long since a dish
was last cooked, capped at 45 days so "ages ago" doesn't become "always", with
never-cooked dishes weighted highest of all and a floor that keeps everything
possible. Over 300 spins against the seeded book that produces roughly:

```
Butter Naan            79   (never cooked)
Tomato Soup            68   (never cooked)
Chole                  65   (last cooked 40 days ago)
…
Poha                    1   (cooked 2 days ago)
```

`weighted: false` gives a flat draw instead.

The response carries the winner in full — so the reveal needs no second call —
plus the slices the wheel should draw and how big the real pool was. `dish` is
null when nothing matched, which is the client's cue to say so rather than spin
an empty wheel.

Two nullable-vs-zero details worth knowing:

* `avoid_recent_days` unset means "use my saved preference"; an explicit `0`
  means "no window, everything is in play". They are different answers, which
  is why the field is nullable rather than defaulting to 0.
* If the avoid-window empties the pool, the spin retries without it. The window
  is a preference, not a rule — telling someone with six dishes that nothing
  matches is worse than repeating one.

## Exports

Every dish comes out three ways:

```
GET /api/dishes/{uuid}/export.md     text/markdown
GET /api/dishes/{uuid}/export.pdf    application/pdf
GET /api/dishes/{uuid}/export.zip    application/zip
POST /api/dishes/import.md           multipart/form-data (`file`)
```

Markdown gets YAML front matter (so a notes app can index it) and mentioned
ingredients in **bold**. The PDF is reportlab/platypus — an ingredient table,
numbered steps with their photos in a column beside them, and a footer on every
page. It is meant to be printed and stuck on a fridge.

Photos are the one thing a markdown file can't hold, so there are two honest
answers rather than one:

* `export.md` links them by presigned URL. One file, renders the instant it is
  pasted anywhere, and the links expire after a week — the S3 v4 maximum.
* `export.zip` is `recipe.md` plus an `images/` folder with relative paths
  (`images/step-03-2.jpg`). Nothing expires, and it drops into an Obsidian
  vault as a folder. This is the one to keep.

Both documents come out of the same renderer with a different URL resolver, so
the two exports cannot drift into disagreeing about what a recipe says.

Markdown import accepts Cookit's own `.md` export and ordinary recipe notes.
Lists below an **Ingredients** heading become ingredients; lists below
**Method**, **Steps**, **Recipe**, **Instructions**, **Directions**, or similar
headings become steps. With no recipe heading, every list outside Ingredients
is treated as steps, including bullet, numbered, alphabetical, and task lists.

Both set `Content-Disposition`, and the app exposes that header through CORS
because the frontend fetches with an `Authorization` header and saves the blob
itself.

## Photos

Dish photos go to MinIO; the row keeps only the object key, and reads hand back
a presigned URL rather than proxying bytes through this process. The first photo
on a dish becomes its cover automatically, deleting the cover promotes the next
one, and deleting a dish removes its objects from storage as well as its rows.

A photo can belong to the dish or to one **step** of it, which is
`dish_images.step_id` — null for the gallery, set for a step. One nullable
column rather than a second table: they are the same thing in storage and differ
only in where they are shown. A step takes any number ("fold it like this, then
like this" is two photos of one instruction), they render beside the step's text
in the app, the PDF and both markdown exports, and they are never eligible to be
the cover — a photo of the onions half-fried is not what the dish looks like.

```
POST /api/steps/{uuid}/images        GET /api/steps/{uuid}/images
```

This is why `PUT /dishes/{uuid}/steps` takes a `step_uuid` per step. Steps used
to be dropped and recreated on every save, which was cheaper to write — but a
step now owns photos, and recreating the row would mean reordering a recipe
silently detached every photo in it. Send the uuid back and the step is edited
in place; omit it and the step is new. Deleting a step hands its photos back to
the dish gallery rather than destroying them.

With storage unreachable, uploads answer 502 and everything else — recipes,
filters, the wheel, the markdown export — carries on. The PDF drops the images
and keeps the recipe.

## Authentik and API Get Away

Authentik proves the user's identity to API Get Away. The gateway then injects
`x-user-sub`, `x-user-email` and `x-user-name` while proxying the request.
Because Cookit also has a direct public URL, those headers alone are spoofable.
`GATEWAY_SHARED_SECRET` proves the request came through API Get Away: the
gateway strips any client-provided `x-api-gateway-secret`, injects the real one,
and Cookit compares it before trusting the user headers.

The secret does not replace Authentik and does not identify users. It
authenticates only the API Gateway → Cookit connection.

### 1. Generate and store the shared value

Generate the value once, then write that same value to every service's Vault
record:

```bash
export NEW_GATEWAY_SHARED_SECRET="$(openssl rand -hex 32)"

vault kv patch apps/api-get-away/api-get-away/env \
  GATEWAY_SHARED_SECRET="$NEW_GATEWAY_SHARED_SECRET"
vault kv patch apps/cookit/cookit/env \
  GATEWAY_SHARED_SECRET="$NEW_GATEWAY_SHARED_SECRET"

unset NEW_GATEWAY_SHARED_SECRET
```

Do not generate separate values per service and do not commit the value. Add
your KV mount prefix to the paths if required by your Vault installation.

### 2. Configure API Get Away

Add the mapping and deployed frontend origin using the authenticated gateway
admin UI/API:

```json
{
  "allowedOrigins": ["https://cookit.krishnarajthadesar.in"],
  "mappings": [
    {"name": "cookit", "backend": "http://100.69.148.22:32042"}
  ]
}
```

Merge these with existing entries instead of replacing the full configuration.
On an existing gateway deployment, active configuration is stored in Postgres;
editing `config.yml` changes only the empty-database bootstrap seed.

### 3. Restart

```bash
kubectl -n api-gateway rollout restart deployment/api-gateway
kubectl -n cookit rollout restart deployment/cookit

kubectl -n cookit rollout status deployment/cookit
```

External Secrets populates `cookit-env` from `apps/cookit/cookit/env`. Confirm
that a 64-character value arrived without printing it:

```bash
kubectl -n cookit get secret cookit-env \
  -o jsonpath='{.data.GATEWAY_SHARED_SECRET}' | base64 -d | wc -c
```

### Account-safe linking flow

1. Existing users continue signing in with their username and password.
2. They select **Profile → Sign-in methods → Link Authentik**.
3. Linking adds an external identity row to the existing user ID; it does not
   modify the password, username, dishes, ingredients or settings.
4. Authentik sign-in succeeds only for a previously linked identity.
5. An unlinked identity cannot automatically create, merge, replace or delete
   an account.

## Deploying

`.gitea/workflows/build-and-push.yml` builds the image, pushes it to the Gitea
registry and writes the new tag into `k8s/overlays/gitea/kustomization.yaml`;
Argo CD watches that path and syncs. `.github/workflows/build-and-push.yml` is
the same pipeline against ghcr.io and the `github` overlay.

Apply **one** of the two Argo CD Applications, not both — they render the same
Deployment, Service and NodePort 32042 into the `cookit` namespace, so running
both leaves two self-healing Applications fighting over the same resources:

```bash
kubectl apply -f k8s/base/argocd-app.yaml          # tracks Gitea
# or
kubectl apply -f k8s/base/argocd-app-github.yaml   # tracks GitHub
```

Required Gitea secret: `REGISTRY_TOKEN`. GitHub uses the built-in
`GITHUB_TOKEN`.

| Service | NodePort |
|---|---|
| cookit | 32042 |

Environment keys are documented in [`.env.example`](.env.example) and supplied
in the cluster by the `cookit-env` ExternalSecret.

## API surface

```
POST   /api/auth/register              POST   /api/auth/login
POST   /api/auth/refresh               POST   /api/auth/logout
GET    /api/auth/me                    PATCH  /api/auth/me
POST   /api/auth/password
POST   /api/auth/authentik/session     GET    /api/auth/authentik
POST   /api/auth/authentik/link        DELETE /api/auth/authentik

GET    /api/ingredients                POST   /api/ingredients
POST   /api/ingredients/bulk           GET    /api/ingredients/suggestions
GET    /api/ingredients/categories
GET    /api/ingredients/{uuid}         PATCH  /api/ingredients/{uuid}
DELETE /api/ingredients/{uuid}

GET    /api/dishes                     POST   /api/dishes
GET    /api/dishes/{uuid}              PATCH  /api/dishes/{uuid}
DELETE /api/dishes/{uuid}
PUT    /api/dishes/{uuid}/ingredients
GET    /api/dishes/{uuid}/steps        PUT    /api/dishes/{uuid}/steps
POST   /api/dishes/{uuid}/pairings     DELETE /api/dishes/{uuid}/pairings/{other}
POST   /api/dishes/{uuid}/cook         GET    /api/dishes/{uuid}/cooks
GET    /api/dishes/{uuid}/export.md    GET    /api/dishes/{uuid}/export.pdf
GET    /api/dishes/{uuid}/export.zip
POST   /api/dishes/import.md

POST   /api/dishes/{uuid}/images       GET    /api/dishes/{uuid}/images
POST   /api/steps/{uuid}/images        GET    /api/steps/{uuid}/images
PATCH  /api/images/{uuid}              DELETE /api/images/{uuid}
GET    /api/images/{uuid}/url

POST   /api/randomizer/spin
GET    /api/stats/dashboard
GET    /api/settings                   PUT    /api/settings
```
