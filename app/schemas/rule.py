from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ValidationInfo, field_validator


class AdditionalParam(Enum):
    NO_RESOLVE = "no-resolve"
    SRC = "src"


class RoutingRuleType(Enum):
    """Enumeration of all Clash rule types"""

    DOMAIN = "DOMAIN"
    DOMAIN_SUFFIX = "DOMAIN-SUFFIX"
    DOMAIN_KEYWORD = "DOMAIN-KEYWORD"
    DOMAIN_REGEX = "DOMAIN-REGEX"
    DOMAIN_WILDCARD = "DOMAIN-WILDCARD"

    GEOSITE = "GEOSITE"
    GEOIP = "GEOIP"

    IP_CIDR = "IP-CIDR"
    IP_CIDR6 = "IP-CIDR6"
    IP_SUFFIX = "IP-SUFFIX"
    IP_ASN = "IP-ASN"

    SRC_GEOIP = "SRC-GEOIP"
    SRC_IP_ASN = "SRC-IP-ASN"
    SRC_IP_CIDR = "SRC-IP-CIDR"
    SRC_IP_SUFFIX = "SRC-IP-SUFFIX"

    DST_PORT = "DST-PORT"
    SRC_PORT = "SRC-PORT"

    IN_PORT = "IN-PORT"
    IN_TYPE = "IN-TYPE"
    IN_USER = "IN-USER"
    IN_NAME = "IN-NAME"

    PROCESS_PATH = "PROCESS-PATH"
    PROCESS_PATH_REGEX = "PROCESS-PATH-REGEX"
    PROCESS_NAME = "PROCESS-NAME"
    PROCESS_NAME_REGEX = "PROCESS-NAME-REGEX"

    UID = "UID"
    NETWORK = "NETWORK"
    DSCP = "DSCP"

    RULE_SET = "RULE-SET"
    AND = "AND"
    OR = "OR"
    NOT = "NOT"
    SUB_RULE = "SUB-RULE"

    MATCH = "MATCH"


class Action(Enum):
    """Enumeration of rule actions"""

    DIRECT = "DIRECT"
    REJECT = "REJECT"
    REJECT_DROP = "REJECT-DROP"
    PASS = "PASS"
    COMPATIBLE = "COMPATIBLE"

    def __str__(self) -> str:
        return self.value


class RuleBase(BaseModel):
    rule_type: RoutingRuleType
    action: Action | str  # Can be Action enum or custom proxy group name
    raw_rule: str

    def to_dict(self) -> dict[str, Any]:
        pass

    def __str__(self) -> str:
        pass

    def __eq__(self, other: RuleBase) -> bool:
        if not isinstance(other, RuleBase):
            return NotImplemented
        return self.__str__() == other.__str__()


class ClashRule(RuleBase):
    """Represents a parsed Clash routing rule"""

    rule_type: RoutingRuleType
    payload: str
    additional_params: AdditionalParam | None = None

    def condition_string(self) -> str:
        return f"{self.rule_type.value},{self.payload}"

    def to_dict(self) -> dict[str, str | None]:
        return {
            "type": self.rule_type.value,
            "payload": self.payload,
            "action": self.action.value
            if isinstance(self.action, Action)
            else self.action,
            "additional_params": self.additional_params.value
            if self.additional_params
            else None,
            "raw": self.raw_rule,
        }

    def __str__(self) -> str:
        rule_str = f"{self.condition_string()},{self.action}"
        if self.additional_params:
            rule_str += f",{self.additional_params.value}"
        return rule_str

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, v: str, values: ValidationInfo) -> str | None:
        if values.data.get(
            "rule_type"
        ) == RoutingRuleType.NETWORK and v.upper() not in (
            "TCP",
            "UDP",
        ):
            raise ValueError("Payload must be TCP or UDP")
        return v


class LogicRule(RuleBase):
    """Represents a logic rule (AND, OR, NOT)"""

    rule_type: Literal[RoutingRuleType.AND, RoutingRuleType.OR, RoutingRuleType.NOT]
    conditions: list[ClashRule | LogicRule]

    def condition_string(self) -> str:
        conditions_str = ",".join(
            [f"({c.condition_string()})" for c in self.conditions]
        )
        return f"{self.rule_type.value},({conditions_str})"

    def to_dict(self) -> dict[str, Any]:
        conditions = []
        for condition in self.conditions:
            conditions.append(condition.condition_string())

        return {
            "type": self.rule_type.value,
            "conditions": conditions,
            "action": self.action.value
            if isinstance(self.action, Action)
            else self.action,
            "raw": self.raw_rule,
        }

    @field_validator("conditions")
    @classmethod
    def validate_conditions(
        cls, v: list[ClashRule | LogicRule]
    ) -> list[ClashRule | LogicRule]:
        if not v:
            raise ValueError("A condition list must be provided")
        return v

    def __str__(self) -> str:
        return f"{self.condition_string()},{self.action}"


class SubRule(RuleBase):
    rule_type: Literal[RoutingRuleType.SUB_RULE] = RoutingRuleType.SUB_RULE
    condition: ClashRule | LogicRule
    action: str

    def condition_string(self) -> str:
        return f"{self.rule_type.value},({self.condition.condition_string()})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.rule_type.value,
            "condition": f"({self.condition.condition_string()})",
            "action": self.action,
            "raw": self.raw_rule,
        }

    def __str__(self) -> str:
        return f"{self.condition_string()},{self.action}"


class MatchRule(RuleBase):
    """Represents a match rule"""

    rule_type: Literal[RoutingRuleType.MATCH] = RoutingRuleType.MATCH

    @staticmethod
    def condition_string() -> str:
        return "MATCH"

    def to_dict(self) -> dict[str, str]:
        return {
            "type": "MATCH",
            "action": self.action.value
            if isinstance(self.action, Action)
            else self.action,
            "raw": self.raw_rule,
        }

    def __str__(self) -> str:
        return f"{self.condition_string()},{self.action}"


RuleType = ClashRule | LogicRule | SubRule | MatchRule
