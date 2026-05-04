from __future__ import annotations

import threading
import time
from typing import Any

import structlog

from pm_bot.core.config_loader import get_clob_creds, get_private_key, get_sizing, load_config

log = structlog.get_logger()

CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137


class ClobTrader:
    def __init__(self, config: dict | None = None) -> None:
        self._config = config or load_config()
        self._client: Any = None
        self._heartbeat_thread: threading.Thread | None = None
        self._heartbeat_id: str = ""
        self._running: bool = False
        self._daily_spent: float = 0.0

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        pk = get_private_key()
        creds_dict = get_clob_creds(self._config)

        if not pk:
            raise ValueError("POLY_PK environment variable is required for trading")

        if not creds_dict["api_key"]:
            raise ValueError("CLOB API credentials not configured. Set [clob] in config.toml or CLOB_API_KEY env var.")

        from py_clob_client_v2 import ApiCreds, ClobClient  # type: ignore[import-untyped]

        creds = ApiCreds(
            api_key=creds_dict["api_key"],
            api_secret=creds_dict["api_secret"],
            api_passphrase=creds_dict["api_passphrase"],
        )
        self._client = ClobClient(
            host=CLOB_HOST,
            chain_id=CHAIN_ID,
            key=pk,
            creds=creds,
        )
        return self._client

    def _check_sizing(self, amount_usd: float) -> str | None:
        sizing = get_sizing(self._config)
        if amount_usd > sizing["max_single"]:
            return f"Amount ${amount_usd:.2f} exceeds max_single ${sizing['max_single']:.2f}"
        if self._daily_spent + amount_usd > sizing["max_daily"]:
            remaining = sizing["max_daily"] - self._daily_spent
            return f"Daily limit ${sizing['max_daily']:.2f} reached (remaining: ${remaining:.2f})"
        return None

    def place_limit_buy(
        self,
        token_id: str,
        price: float,
        size: float,
        tick_size: str = "0.01",
        neg_risk: bool = True,
    ) -> dict | None:
        amount_usd = price * size
        err = self._check_sizing(amount_usd)
        if err:
            log.error("sizing_check_failed", error=err)
            return None

        try:
            from py_clob_client_v2 import OrderArgs, OrderType, PartialCreateOrderOptions  # type: ignore[import-untyped]
            from py_clob_client_v2.order_builder.constants import BUY  # type: ignore[import-untyped]

            client = self._get_client()
            response = client.create_and_post_order(  # type: ignore[attr-defined]
                order_args=OrderArgs(
                    token_id=token_id,
                    price=price,
                    size=size,
                    side=BUY,
                ),
                options=PartialCreateOrderOptions(
                    tick_size=tick_size,
                    neg_risk=neg_risk,
                ),
                order_type=OrderType.GTC,
            )
            self._daily_spent += amount_usd
            log.info("order_placed", token_id=token_id, side="BUY", price=price, size=size, response=response)
            return response  # type: ignore[no-any-return]
        except Exception as e:
            log.error("order_failed", token_id=token_id, error=str(e))
            return None

    def place_limit_sell(
        self,
        token_id: str,
        price: float,
        size: float,
        tick_size: str = "0.01",
        neg_risk: bool = True,
    ) -> dict | None:
        amount_usd = price * size
        err = self._check_sizing(amount_usd)
        if err:
            log.error("sizing_check_failed", error=err)
            return None

        try:
            from py_clob_client_v2 import OrderArgs, OrderType, PartialCreateOrderOptions  # type: ignore[import-untyped]
            from py_clob_client_v2.order_builder.constants import SELL  # type: ignore[import-untyped]

            client = self._get_client()
            response = client.create_and_post_order(  # type: ignore[attr-defined]
                order_args=OrderArgs(
                    token_id=token_id,
                    price=price,
                    size=size,
                    side=SELL,
                ),
                options=PartialCreateOrderOptions(
                    tick_size=tick_size,
                    neg_risk=neg_risk,
                ),
                order_type=OrderType.GTC,
            )
            log.info("order_placed", token_id=token_id, side="SELL", price=price, size=size)
            return response  # type: ignore[no-any-return]
        except Exception as e:
            log.error("order_failed", token_id=token_id, error=str(e))
            return None

    def place_market_buy(
        self,
        token_id: str,
        amount: float,
        price: float = 0.99,
        tick_size: str = "0.01",
        neg_risk: bool = True,
    ) -> dict | None:
        err = self._check_sizing(amount)
        if err:
            log.error("sizing_check_failed", error=err)
            return None

        try:
            from py_clob_client_v2 import MarketOrderArgs, OrderType, PartialCreateOrderOptions  # type: ignore[import-untyped]
            from py_clob_client_v2.order_builder.constants import BUY  # type: ignore[import-untyped]

            client = self._get_client()
            response = client.create_and_post_market_order(  # type: ignore[attr-defined]
                order_args=MarketOrderArgs(
                    token_id=token_id,
                    side=BUY,
                    amount=amount,
                    price=price,
                ),
                options=PartialCreateOrderOptions(
                    tick_size=tick_size,
                    neg_risk=neg_risk,
                ),
                order_type=OrderType.FOK,
            )
            self._daily_spent += amount
            log.info("market_order_placed", token_id=token_id, side="BUY", amount=amount, response=response)
            return response  # type: ignore[no-any-return]
        except Exception as e:
            log.error("market_order_failed", token_id=token_id, error=str(e))
            return None

    def cancel_order(self, order_id: str) -> dict | None:
        try:
            from py_clob_client_v2 import OrderPayload  # type: ignore[import-untyped]

            client = self._get_client()
            response = client.cancel_order(OrderPayload(orderID=order_id))  # type: ignore[attr-defined]
            log.info("order_cancelled", order_id=order_id)
            return response  # type: ignore[no-any-return]
        except Exception as e:
            log.error("cancel_failed", order_id=order_id, error=str(e))
            return None

    def cancel_all_orders(self) -> dict | None:
        try:
            client = self._get_client()
            response = client.cancel_all()  # type: ignore[attr-defined]
            log.info("all_orders_cancelled")
            return response  # type: ignore[no-any-return]
        except Exception as e:
            log.error("cancel_all_failed", error=str(e))
            return None

    def get_open_orders(self, market: str | None = None) -> list[dict]:
        try:
            from py_clob_client_v2 import OpenOrderParams  # type: ignore[import-untyped]

            client = self._get_client()
            params = OpenOrderParams(market=market) if market else None
            orders = client.get_open_orders(params)  # type: ignore[attr-defined]
            return orders if isinstance(orders, list) else []  # type: ignore[no-any-return]
        except Exception as e:
            log.error("get_orders_failed", error=str(e))
            return []

    def get_order_status(self, order_id: str) -> dict | None:
        try:
            client = self._get_client()
            return client.get_order(order_id)  # type: ignore[attr-defined,no-any-return]
        except Exception as e:
            log.error("get_order_failed", order_id=order_id, error=str(e))
            return None

    def get_trades(self, market: str | None = None) -> list[dict]:
        try:
            from py_clob_client_v2 import TradeParams  # type: ignore[import-untyped]

            client = self._get_client()
            params = TradeParams(market=market) if market else None
            trades = client.get_trades(params)  # type: ignore[attr-defined]
            return trades if isinstance(trades, list) else []  # type: ignore[no-any-return]
        except Exception as e:
            log.error("get_trades_failed", error=str(e))
            return []

    def is_neg_risk_market(self, token_id: str) -> bool:
        try:
            client = self._get_client()
            result = client.get_neg_risk(token_id)  # type: ignore[attr-defined]
            return bool(result)
        except Exception as e:
            log.warning("neg_risk_check_failed", token_id=token_id, error=str(e))
            return True

    def start_heartbeat(self) -> None:
        self._running = True
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()
        log.info("heartbeat_started")

    def stop_heartbeat(self) -> None:
        self._running = False
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=3)
        log.info("heartbeat_stopped")

    def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                client = self._get_client()
                resp = client.post_heartbeat(self._heartbeat_id)  # type: ignore[attr-defined]
                if isinstance(resp, dict) and "heartbeat_id" in resp:
                    self._heartbeat_id = resp["heartbeat_id"]
            except Exception as e:
                log.warning("heartbeat_error", error=str(e))
            time.sleep(5)

    @property
    def daily_spent(self) -> float:
        return self._daily_spent

    def is_configured(self) -> bool:
        pk = get_private_key()
        creds = get_clob_creds(self._config)
        return bool(pk and creds["api_key"])
