"""Subscription billing and usage metering for SharipovAI SaaS."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import stripe
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth_saas import ensure_same_origin, require_current_user
from .db_saas import SessionLocal
from .models_saas import ChatMessageLog, Subscription, User
from .settings_saas import get_saas_settings

settings = get_saas_settings()
if settings.stripe_secret_key:
    stripe.api_key = settings.stripe_secret_key

_ACTIVE_STATUSES = {"active", "trialing"}


class CheckoutSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    checkout_url: str | None = None
    portal_url: str | None = None


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _month_floor(value: datetime) -> datetime:
    value = value.astimezone(UTC)
    return datetime(value.year, value.month, 1, tzinfo=UTC)


def ensure_usage_period(user: User) -> None:
    now_floor = _month_floor(_utcnow())
    current = _month_floor(user.current_period_started_at or _utcnow())
    if current != now_floor:
        user.current_period_started_at = now_floor
        user.messages_used_this_period = 0


def subscription_allows_messages(subscription: Subscription | None) -> bool:
    if not subscription:
        return False
    if subscription.status not in _ACTIVE_STATUSES:
        return False
    return subscription.current_period_end is None or subscription.current_period_end > _utcnow()


def get_or_create_subscription(db: Session, user: User) -> Subscription:
    if user.subscription:
        return user.subscription
    subscription = Subscription(user=user, provider="stripe", plan_code="free", status="free")
    db.add(subscription)
    db.flush()
    return subscription


def usage_snapshot(user: User, subscription: Subscription | None) -> dict[str, Any]:
    ensure_usage_period(user)
    paid = subscription_allows_messages(subscription)
    limit = None if paid else int(user.free_messages_limit or settings.free_messages_per_month)
    can_send = paid or user.messages_used_this_period < (limit or 0)
    plan = subscription.plan_code if subscription else "free"
    status = subscription.status if subscription else "free"
    current_period_end = subscription.current_period_end.isoformat() if subscription and subscription.current_period_end else None
    return {
        "status": "ok",
        "plan_code": plan,
        "subscription_status": status,
        "messages_used_this_period": user.messages_used_this_period,
        "message_limit": limit,
        "can_send_messages": can_send,
        "current_period_started_at": user.current_period_started_at.isoformat(),
        "current_period_end": current_period_end,
        "stripe_publishable_key": settings.stripe_publishable_key or None,
    }


def assert_message_access(db: Session, user: User) -> dict[str, Any]:
    subscription = get_or_create_subscription(db, user)
    snapshot = usage_snapshot(user, subscription)
    if not snapshot["can_send_messages"]:
        raise HTTPException(
            status_code=403,
            detail={
                "status": "subscription_required",
                "message": "Лимит бесплатных сообщений исчерпан. Оформите подписку, чтобы продолжить.",
            },
        )
    return snapshot


def record_chat_completion(
    db: Session,
    user: User,
    *,
    user_message: str,
    assistant_message: str,
    model_name: str,
    request_id: str,
) -> None:
    subscription = get_or_create_subscription(db, user)
    snapshot = usage_snapshot(user, subscription)
    if not subscription_allows_messages(subscription):
        limit = snapshot["message_limit"] or settings.free_messages_per_month
        user.messages_used_this_period = min(limit, user.messages_used_this_period + 1)
    db.add(
        ChatMessageLog(
            user=user,
            role="user",
            content=user_message,
            model_name=model_name,
            request_id=request_id,
            source="gemini",
        )
    )
    db.add(
        ChatMessageLog(
            user=user,
            role="assistant",
            content=assistant_message,
            model_name=model_name,
            request_id=request_id,
            source="gemini",
        )
    )
    db.flush()


def _subscription_from_provider_id(db: Session, provider_subscription_id: str) -> Subscription | None:
    return db.scalar(
        select(Subscription).where(Subscription.provider_subscription_id == provider_subscription_id)
    )


def _timestamp_to_datetime(value: int | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromtimestamp(value, tz=UTC)


def sync_subscription_from_stripe_event(db: Session, payload: dict[str, Any]) -> None:
    customer_id = str(payload.get("customer", "") or "")
    subscription_id = str(payload.get("id", "") or payload.get("subscription", "") or "")
    client_reference_id = str(payload.get("client_reference_id", "") or payload.get("metadata", {}).get("user_id", "") or "")

    subscription = None
    if subscription_id:
        subscription = _subscription_from_provider_id(db, subscription_id)
    if not subscription and client_reference_id:
        user = db.get(User, client_reference_id)
        if user:
            subscription = get_or_create_subscription(db, user)
    if not subscription:
        return

    subscription.provider = "stripe"
    if customer_id:
        subscription.provider_customer_id = customer_id
    if subscription_id:
        subscription.provider_subscription_id = subscription_id
    subscription.plan_code = "pro_monthly"
    subscription.status = str(payload.get("status", "active") or "active")
    subscription.cancel_at_period_end = bool(payload.get("cancel_at_period_end", False))
    subscription.current_period_end = _timestamp_to_datetime(payload.get("current_period_end"))
    db.flush()


def _checkout_urls(request: Request) -> tuple[str, str]:
    base = settings.app_base_url or f"{request.url.scheme}://{request.headers.get('host', '127.0.0.1')}"
    return f"{base}/?checkout=success", f"{base}/?checkout=canceled"


def install_saas_billing_api(app: FastAPI) -> None:
    if getattr(app.state, "saas_billing_api_installed", False):
        return
    app.state.saas_billing_api_installed = True

    @app.get("/api/billing/status")
    async def billing_status(request: Request) -> dict[str, Any]:
        db = SessionLocal()
        try:
            user = require_current_user(request, db)
            subscription = get_or_create_subscription(db, user)
            snapshot = usage_snapshot(user, subscription)
            db.commit()
            return snapshot
        finally:
            db.close()

    @app.post("/api/billing/checkout-session", response_model=CheckoutSessionResponse)
    async def billing_checkout(request: Request) -> CheckoutSessionResponse:
        ensure_same_origin(request)
        if not settings.stripe_secret_key or not settings.stripe_monthly_price_id:
            raise HTTPException(status_code=503, detail={"status": "billing_not_configured", "message": "Stripe ещё не настроен."})
        db = SessionLocal()
        try:
            user = require_current_user(request, db)
            subscription = get_or_create_subscription(db, user)
            success_url, cancel_url = _checkout_urls(request)
            customer_id = subscription.provider_customer_id or None
            if not customer_id:
                customer = stripe.Customer.create(email=user.email, name=user.display_name or None, metadata={"user_id": user.id})
                customer_id = str(customer["id"])
                subscription.provider_customer_id = customer_id
                db.flush()
            session = stripe.checkout.Session.create(
                mode="subscription",
                customer=customer_id,
                line_items=[{"price": settings.stripe_monthly_price_id, "quantity": 1}],
                success_url=success_url,
                cancel_url=cancel_url,
                client_reference_id=user.id,
                metadata={"user_id": user.id},
                allow_promotion_codes=True,
            )
            db.commit()
            return CheckoutSessionResponse(status="ok", checkout_url=str(session["url"]))
        finally:
            db.close()

    @app.post("/api/billing/portal-session", response_model=CheckoutSessionResponse)
    async def billing_portal(request: Request) -> CheckoutSessionResponse:
        ensure_same_origin(request)
        if not settings.stripe_secret_key:
            raise HTTPException(status_code=503, detail={"status": "billing_not_configured"})
        db = SessionLocal()
        try:
            user = require_current_user(request, db)
            subscription = get_or_create_subscription(db, user)
            if not subscription.provider_customer_id:
                raise HTTPException(status_code=409, detail={"status": "billing_customer_missing", "message": "Сначала оформите подписку."})
            portal = stripe.billing_portal.Session.create(
                customer=subscription.provider_customer_id,
                return_url=f"{settings.app_base_url}/",
            )
            return CheckoutSessionResponse(status="ok", portal_url=str(portal["url"]))
        finally:
            db.close()

    @app.post("/api/billing/webhook")
    async def billing_webhook(request: Request) -> dict[str, str]:
        if not settings.stripe_webhook_secret:
            raise HTTPException(status_code=503, detail={"status": "billing_not_configured"})
        payload = await request.body()
        signature = request.headers.get("stripe-signature", "")
        try:
            event = stripe.Webhook.construct_event(payload=payload, sig_header=signature, secret=settings.stripe_webhook_secret)
        except Exception as exc:
            raise HTTPException(status_code=400, detail={"status": "invalid_signature"}) from exc
        db = SessionLocal()
        try:
            event_type = str(event.get("type", ""))
            data_object = dict(event.get("data", {}).get("object", {}) or {})
            if event_type == "checkout.session.completed":
                if data_object.get("subscription"):
                    subscription_payload = stripe.Subscription.retrieve(str(data_object["subscription"]))
                    sync_subscription_from_stripe_event(db, dict(subscription_payload))
            elif event_type in {"customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"}:
                sync_subscription_from_stripe_event(db, data_object)
            elif event_type == "invoice.payment_failed":
                subscription_id = str(data_object.get("subscription", "") or "")
                subscription = _subscription_from_provider_id(db, subscription_id)
                if subscription:
                    subscription.status = "past_due"
            elif event_type == "invoice.paid":
                subscription_id = str(data_object.get("subscription", "") or "")
                if subscription_id:
                    subscription_payload = stripe.Subscription.retrieve(subscription_id)
                    sync_subscription_from_stripe_event(db, dict(subscription_payload))
            db.commit()
            return {"status": "ok"}
        finally:
            db.close()


__all__ = [
    "assert_message_access",
    "ensure_usage_period",
    "get_or_create_subscription",
    "install_saas_billing_api",
    "record_chat_completion",
    "subscription_allows_messages",
    "usage_snapshot",
]
