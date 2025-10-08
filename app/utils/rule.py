import ipaddress
import re

from mitmproxy.http import HTTPFlow
from mitmproxy.tcp import TCPFlow

from app.schemas import ClashRule, LogicRule, MatchRule, RoutingRuleType, RuleType


class MatchingUtils:
    @staticmethod
    def match_port(rule_payload: str, port: int):
        port_rules = re.split(r"[,/]", rule_payload)
        for port_rule in port_rules:
            if "-" in port_rule:
                try:
                    start, end = map(int, port_rule.split("-"))
                    if start <= port <= end:
                        return True
                except ValueError:
                    continue  # Handle potential malformed range
            else:
                try:
                    if port == int(port_rule):
                        return True
                except ValueError:
                    continue  # Handle potential malformed port
        return False

    @staticmethod
    def match_ip(ip: str, rule_payload) -> bool:
        try:
            ip_addr = ipaddress.ip_address(ip)
            ip_net = ipaddress.ip_network(rule_payload, strict=False)
            return ip_addr in ip_net
        except ValueError:
            return False

    @staticmethod
    def match_ip_suffix(ip: str, rule_payload) -> bool:
        try:
            # Parse payload like "192.168.1.201/8"
            payload_ip_str, suffix_len_str = rule_payload.split("/")
            suffix_len = int(suffix_len_str)

            # Convert IPs to integers
            flow_ip = ipaddress.ip_address(ip)
            payload_ip = ipaddress.ip_address(payload_ip_str)

            if flow_ip.version != payload_ip.version:
                return False

            flow_ip_int = int(flow_ip)
            payload_ip_int = int(payload_ip)

            # Create a bitmask for the least significant bits
            mask = (1 << suffix_len) - 1

            # Compare the least significant bits
            return (flow_ip_int & mask) == (payload_ip_int & mask)
        except (ValueError, IndexError):
            # Handle malformed rule_payload or invalid IPs
            return False


class HttpFlowMatcher:
    @staticmethod
    def matches(rule: RuleType, flow: HTTPFlow) -> bool:
        if isinstance(rule, ClashRule):
            match rule.rule_type:
                case RoutingRuleType.DOMAIN:
                    return flow.request.pretty_host == rule.payload
                case RoutingRuleType.DOMAIN_KEYWORD:
                    return rule.payload in flow.request.pretty_host
                case RoutingRuleType.DOMAIN_SUFFIX:
                    return flow.request.pretty_host.endswith(rule.payload)
                case RoutingRuleType.DOMAIN_REGEX:
                    return re.match(rule.payload, flow.request.pretty_host) is not None
                case RoutingRuleType.DOMAIN_WILDCARD:
                    # Convert wildcard to regex
                    payload = rule.payload
                    if payload.startswith("*."):
                        # *.baidu.com matches tieba.baidu.com but not 123.tieba.baidu.com or baidu.com
                        # So, it should match one level of subdomain.
                        # The regex should be something like `^[^\.]+\.baidu\.com$`
                        domain = payload[2:]
                        pattern = r"^[^\.]+\." + re.escape(domain) + "$"
                        return re.match(pattern, flow.request.pretty_host) is not None
                    elif payload.startswith("+."):
                        # +.baidu.com matches tieba.baidu.com, 123.tieba.baidu.com, and baidu.com
                        # This is similar to DOMAIN-SUFFIX
                        domain = payload[2:]
                        return flow.request.pretty_host.endswith(domain)
                    elif payload.startswith("."):
                        # .baidu.com matches tieba.baidu.com and 123.tieba.baidu.com, but does not match baidu.com
                        domain = payload[1:]
                        return (
                            flow.request.pretty_host.endswith(domain)
                            and flow.request.pretty_host != domain
                        )
                    else:
                        # Fallback for other wildcard cases, e.g. "example.com"
                        pattern = rule.payload.replace(".", r"\.").replace("*", ".*")
                        return re.match(pattern, flow.request.pretty_host) is not None
                case RoutingRuleType.DST_PORT:
                    port = flow.request.port
                    MatchingUtils.match_port(rule.payload, port)
                case RoutingRuleType.SRC_PORT:
                    if not flow.client_conn.peername:
                        return False
                    port = flow.client_conn.peername[1]
                    MatchingUtils.match_port(rule.payload, port)
                case RoutingRuleType.IP_CIDR:
                    if not flow.server_conn.peername:
                        return False
                    peer_name = flow.server_conn.peername
                    # rule.payload e.g. 127.0.0.0/8, 2620:0:2d0:200::7/32
                    return MatchingUtils.match_ip(
                        peer_name[0], rule_payload=rule.payload
                    )
                case RoutingRuleType.IP_SUFFIX:
                    if not flow.server_conn.peername:
                        return False
                    peer_name = flow.server_conn.peername
                    # rule.payload e.g. 192.168.1.201/8
                    return MatchingUtils.match_ip_suffix(
                        peer_name[0], rule_payload=rule.payload
                    )
                case RoutingRuleType.SRC_IP_CIDR:
                    if not flow.client_conn.peername:
                        return False
                    peer_name = flow.client_conn.peername
                    return MatchingUtils.match_ip(
                        peer_name[0], rule_payload=rule.payload
                    )
                case RoutingRuleType.SRC_IP_SUFFIX:
                    if not flow.client_conn.peername:
                        return False
                    peer_name = flow.client_conn.peername
                    return MatchingUtils.match_ip_suffix(
                        peer_name[0], rule_payload=rule.payload
                    )
                case _:
                    return False
        elif isinstance(rule, LogicRule):
            match rule.rule_type:
                case RoutingRuleType.AND:
                    for condition in rule.conditions:
                        if not HttpFlowMatcher.matches(condition, flow):
                            return False
                    return True
                case RoutingRuleType.OR:
                    for condition in rule.conditions:
                        if HttpFlowMatcher.matches(condition, flow):
                            return True
                    return False
                case RoutingRuleType.NOT:
                    for condition in rule.conditions:
                        return not HttpFlowMatcher.matches(condition, flow)
                    return False
                case _:
                    return False
        elif isinstance(rule, MatchRule):
            return True
        return False


class TcpFlowMatcher:
    @staticmethod
    def matches(rule: RuleType, flow: TCPFlow) -> bool:
        # TODO
        return False


class Matcher:
    @staticmethod
    def matches(rule: RuleType, flow: HTTPFlow | TCPFlow) -> bool:
        if isinstance(flow, HTTPFlow):
            return HttpFlowMatcher.matches(rule, flow)
        elif isinstance(flow, TCPFlow):
            return TcpFlowMatcher.matches(rule, flow)
        return False
