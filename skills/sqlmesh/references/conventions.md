# Conventions

> Project defaults. The user or an existing project pattern overrides these —
> ask the user how their existing models are named and follow that.

## One model per question

```
  analytics.<subject>_<grain>   one model, one query. reads source tables
                                directly. intermediate steps are CTEs.
                                select only the columns the question needs.
```

No staging, intermediate or marts layers. Every extra model is another
validation, and `validate` would have to receive every upstream model's SQL
again. Add a separate staging model only when the user explicitly asks for a
reusable layer.

## Names

```
  snake_case everywhere
  _at          timestamps          placed_at
  _date        dates               order_date
  is_ / has_   booleans            is_active, has_prior_order
  _count       counts              order_count
  _rate        0–1                 conversion_rate
  _pct         0–100               churn_pct
  _id          keys                customer_id
```

Name a mart for its grain: `revenue_by_region_month`, `customer_daily`.

## Output

The answer is a fenced ```sql code block in the reply — never a file, never a
file path. The person saves it where their project wants it.

## Every model has

`kind` explicit · `grain` · `description` · at least one meaningful audit ·
every output column cast and aliased.
