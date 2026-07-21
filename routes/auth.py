"""
Authentication routes: login, logout, change password.
"""

import logging
from datetime import datetime, timezone, timedelta
from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request, session, jsonify
)
from flask_login import login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField
from wtforms.validators import DataRequired, Length, EqualTo

from models.database import db, User
from utils.helpers import sanitize_string

logger = logging.getLogger(__name__)
auth_bp = Blueprint("auth", __name__)

MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


# ─────────────────────────────────────────────────────────────────────────────
# Forms
# ─────────────────────────────────────────────────────────────────────────────

class LoginForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(1, 80)])
    password = PasswordField("Password", validators=[DataRequired(), Length(1, 200)])
    remember = BooleanField("Remember me")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("Current Password", validators=[DataRequired()])
    new_password = PasswordField(
        "New Password",
        validators=[DataRequired(), Length(min=8, message="Minimum 8 characters")],
    )
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[DataRequired(), EqualTo("new_password", message="Passwords must match")],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Handle admin login with brute-force protection."""
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        username = sanitize_string(form.username.data)
        password = form.password.data

        user = User.query.filter_by(username=username).first()

        if not user:
            flash("Invalid username or password.", "danger")
            logger.warning(f"Failed login attempt for unknown user: {username}")
            return render_template("login.html", form=form)

        # Check account lock
        if user.is_locked():
            flash(f"Account temporarily locked. Try again in {LOCKOUT_MINUTES} minutes.", "danger")
            return render_template("login.html", form=form)

        if not user.check_password(password):
            user.login_attempts = (user.login_attempts or 0) + 1
            if user.login_attempts >= MAX_LOGIN_ATTEMPTS:
                user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)
                flash(f"Too many failed attempts. Account locked for {LOCKOUT_MINUTES} minutes.", "danger")
                logger.warning(f"Account locked: {username}")
            else:
                remaining = MAX_LOGIN_ATTEMPTS - user.login_attempts
                flash(f"Invalid password. {remaining} attempts remaining.", "danger")
            user.save()
            return render_template("login.html", form=form)

        # Successful login
        user.login_attempts = 0
        user.locked_until = None
        user.last_login = datetime.now(timezone.utc)
        user.save()

        login_user(user, remember=form.remember.data)
        session.permanent = True
        logger.info(f"Successful login: {username}")

        next_page = request.args.get("next")
        if next_page and next_page.startswith("/"):
            return redirect(next_page)
        return redirect(url_for("main.dashboard"))

    return render_template("login.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    """Handle user logout."""
    logger.info(f"User logged out: {current_user.username}")
    logout_user()
    flash("You have been logged out successfully.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    """Handle password change."""
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash("Current password is incorrect.", "danger")
            return render_template("change_password.html", form=form)

        current_user.set_password(form.new_password.data)
        current_user.save()
        flash("Password changed successfully.", "success")
        logger.info(f"Password changed for user: {current_user.username}")
        return redirect(url_for("main.dashboard"))

    return render_template("change_password.html", form=form)