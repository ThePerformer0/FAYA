# Organisation des tests Backend (CDC §18)

- `unit/` : tests unitaires de règles métier pures, modèles, contraintes et validateurs (`pytest -m unit`).
- `integration/` : tests d'API REST, flux complets sur PostgreSQL/PostGIS réel, permissions et isolation multi-dépôts (`pytest -m integration`).
- `concurrency/` : tests multi-threads avec `@pytest.mark.django_db(transaction=True)` et `ThreadPoolExecutor` (`pytest -m concurrency`).

Les tests E2E et PWA (Playwright, Jalon 5) sont placés dans `e2e/` à la racine du dépôt.
