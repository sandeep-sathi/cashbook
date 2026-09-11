import csv
import io
import sqlite3
from datetime import date

from flask import Flask, flash, g, redirect, render_template, request, Response, url_for

import db
import validation

app = Flask(__name__)
app.secret_key = "dev"

app.teardown_appcontext(db.close_db)


@app.template_filter("money")
def money_filter(cents):
    return f"{cents / 100:,.2f}"


@app.route("/")
def index():
    return redirect(url_for("businesses"))


@app.route("/businesses", methods=["GET", "POST"])
def businesses():
    if request.method == "POST":
        try:
            name = validation.validate_business_name(request.form.get("name"))
            business_id = db.create_business(name)
            return redirect(url_for("ledger", business_id=business_id))
        except sqlite3.IntegrityError:
            flash("A business with that name already exists.")
        except ValueError as e:
            flash(str(e))
        return render_template(
            "businesses.html",
            businesses=db.list_businesses(),
            form_name=request.form.get("name", ""),
        )

    return render_template("businesses.html", businesses=db.list_businesses(), form_name="")


def _filter_args():
    return {
        "date_from": request.args.get("date_from") or None,
        "date_to": request.args.get("date_to") or None,
        "category_id": request.args.get("category_id") or None,
        "q": request.args.get("q") or None,
    }


@app.route("/businesses/<int:business_id>/ledger")
def ledger(business_id):
    business = db.get_business(business_id)
    if business is None:
        flash("Business not found.")
        return redirect(url_for("businesses"))

    filters = _filter_args()
    rows = db.list_transactions(business_id, **filters)

    total_in = sum(r["amount_cents"] for r in rows if r["type"] == "in")
    total_out = sum(r["amount_cents"] for r in rows if r["type"] == "out")

    query_args = {k: v for k, v in filters.items() if v}

    return render_template(
        "ledger.html",
        business=business,
        transactions=rows,
        categories=db.list_categories(business_id),
        filters=filters,
        query_args=query_args,
        total_in=total_in,
        total_out=total_out,
        net=total_in - total_out,
    )


@app.route("/businesses/<int:business_id>/transactions/new", methods=["GET", "POST"])
def new_transaction(business_id):
    business = db.get_business(business_id)
    if business is None:
        flash("Business not found.")
        return redirect(url_for("businesses"))

    if request.method == "POST":
        try:
            txn_date = validation.parse_date(request.form.get("date"))
            txn_type = validation.validate_type(request.form.get("type"))
            amount_cents = validation.parse_amount(request.form.get("amount"))
            category_name = validation.clean_category_name(request.form.get("category"))
            description = validation.clean_description(request.form.get("description"))
            category_id = db.get_or_create_category(business_id, category_name)
            db.create_transaction(
                business_id, txn_date, txn_type, amount_cents, category_id, description
            )
            return redirect(url_for("ledger", business_id=business_id))
        except ValueError as e:
            flash(str(e))
            return render_template(
                "transaction_form.html",
                business=business,
                action="new",
                txn=request.form,
                business_categories=db.list_categories(business_id),
            )

    return render_template(
        "transaction_form.html",
        business=business,
        action="new",
        txn={"date": date.today().isoformat(), "type": "in"},
        business_categories=db.list_categories(business_id),
    )


@app.route("/businesses/<int:business_id>/transactions/<int:txn_id>/edit", methods=["GET", "POST"])
def edit_transaction(business_id, txn_id):
    business = db.get_business(business_id)
    if business is None:
        flash("Business not found.")
        return redirect(url_for("businesses"))

    txn = db.get_transaction(business_id, txn_id)
    if txn is None:
        flash("Transaction not found.")
        return redirect(url_for("ledger", business_id=business_id))

    if request.method == "POST":
        try:
            txn_date = validation.parse_date(request.form.get("date"))
            txn_type = validation.validate_type(request.form.get("type"))
            amount_cents = validation.parse_amount(request.form.get("amount"))
            category_name = validation.clean_category_name(request.form.get("category"))
            description = validation.clean_description(request.form.get("description"))
            category_id = db.get_or_create_category(business_id, category_name)
            db.update_transaction(
                business_id, txn_id, txn_date, txn_type, amount_cents, category_id, description
            )
            return redirect(url_for("ledger", business_id=business_id))
        except ValueError as e:
            flash(str(e))
            return render_template(
                "transaction_form.html",
                business=business,
                action="edit",
                txn=request.form,
                txn_id=txn_id,
                business_categories=db.list_categories(business_id),
            )

    category_row = None
    if txn["category_id"]:
        category_row = next(
            (c for c in db.list_categories(business_id) if c["id"] == txn["category_id"]), None
        )
    form_values = {
        "date": txn["date"],
        "type": txn["type"],
        "amount": f"{txn['amount_cents'] / 100:.2f}",
        "category": category_row["name"] if category_row else "",
        "description": txn["description"] or "",
    }
    return render_template(
        "transaction_form.html",
        business=business,
        action="edit",
        txn=form_values,
        txn_id=txn_id,
        business_categories=db.list_categories(business_id),
    )


@app.route("/businesses/<int:business_id>/transactions/<int:txn_id>/delete", methods=["POST"])
def delete_transaction(business_id, txn_id):
    db.delete_transaction(business_id, txn_id)
    return redirect(url_for("ledger", business_id=business_id))


@app.route("/businesses/<int:business_id>/export.csv")
def export_csv(business_id):
    business = db.get_business(business_id)
    if business is None:
        flash("Business not found.")
        return redirect(url_for("businesses"))

    filters = _filter_args()
    rows = db.list_transactions(business_id, **filters)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Date", "Type", "Category", "Description", "Amount", "Running Balance"])
    for r in rows:
        writer.writerow(
            [
                r["date"],
                r["type"],
                r["category_name"] or "",
                r["description"] or "",
                f"{r['amount_cents'] / 100:.2f}",
                f"{r['running_balance_cents'] / 100:.2f}",
            ]
        )

    safe_name = "".join(c for c in business["name"] if c.isalnum() or c in " -_").strip() or "business"
    filename = f"{safe_name}_{date.today().isoformat()}.csv"
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
