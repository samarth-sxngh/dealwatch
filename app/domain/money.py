"""Domain Money type with currency binding and strict equality/comparison rules."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import ClassVar, Self


class CurrencyMismatchError(ValueError):
    """Raised when comparing or operating on different currencies without explicit conversion."""

    def __init__(self, currency_a: str, currency_b: str) -> None:
        super().__init__(
            f"Cannot compare or operate on mismatching currencies: '{currency_a}' and '{currency_b}'. "
            "DealWatch never converts currencies for price tracking."
        )


class Money:
    """Immutable representation of a monetary value bound to an ISO 4217 currency code."""

    __slots__ = ("_amount", "_currency")

    CURRENCY_SYMBOLS: ClassVar[dict[str, str]] = {
        "INR": "₹",
        "USD": "$",
        "GBP": "£",
        "EUR": "€",
        "CAD": "CA$",
        "AUD": "A$",
        "JPY": "¥",
    }

    def __init__(self, amount: Decimal | str | float, currency: str) -> None:
        if not currency or not isinstance(currency, str):
            raise ValueError("Currency must be a non-empty string ISO code.")
        clean_currency = currency.strip().upper()
        if len(clean_currency) != 3:
            raise ValueError(f"Invalid ISO currency code: '{currency}'. Expected 3 letters.")

        try:
            # Always quantize to 2 decimal places using Decimal
            dec_amount = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, TypeError) as exc:
            raise ValueError(f"Invalid monetary amount: {amount}") from exc

        self._amount = dec_amount
        self._currency = clean_currency

    @property
    def amount(self) -> Decimal:
        return self._amount

    @property
    def currency(self) -> str:
        return self._currency

    def __repr__(self) -> str:
        return f"Money({self._amount}, '{self._currency}')"

    def __str__(self) -> str:
        symbol = self.CURRENCY_SYMBOLS.get(self._currency, f"{self._currency} ")
        return f"{symbol}{self._amount:,.2f}"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return False
        return self._amount == other._amount and self._currency == other._currency

    def _check_currency(self, other: "Money") -> None:
        if self._currency != other._currency:
            raise CurrencyMismatchError(self._currency, other._currency)

    def __lt__(self, other: "Money") -> bool:
        self._check_currency(other)
        return self._amount < other._amount

    def __le__(self, other: "Money") -> bool:
        self._check_currency(other)
        return self._amount <= other._amount

    def __gt__(self, other: "Money") -> bool:
        self._check_currency(other)
        return self._amount > other._amount

    def __ge__(self, other: "Money") -> bool:
        self._check_currency(other)
        return self._amount >= other._amount

    def __add__(self, other: "Money") -> Self:
        self._check_currency(other)
        return self.__class__(self._amount + other._amount, self._currency)

    def __sub__(self, other: "Money") -> Self:
        self._check_currency(other)
        return self.__class__(self._amount - other._amount, self._currency)

    def difference_amount(self, other: "Money") -> Decimal:
        """Returns the absolute difference amount between two Money values."""
        self._check_currency(other)
        return abs(self._amount - other._amount)
