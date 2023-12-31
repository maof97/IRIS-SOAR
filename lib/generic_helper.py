# IRIS-SOAR
# Created by: Martin Offermann
# This module is a helper module that provides multiple generic funtions that can be used all over IRIS-SOAR.
# These functions are not integration specific. For integration specific functions, please use the playbook building blocks (BB) in the playbooks folder.

import lib.logging_helper as logging_helper
import lib.config_helper as config_helper

import json
from functools import reduce
import pandas as pd
import base64
import datetime
import ipaddress
from typing import Union, List
import re
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from collections import deque
from uuid import UUID


THRESHOLD_MAX_CONTEXTS = 1000  # The maximum number of contexts for each type that can be added to a alert case

mlog = logging_helper.Log("lib.generic_helper")


def dict_get(dictionary, keys, default=None):
    """Gets a value from a nested dictionary.

    Args:
        dictionary (dict): The dictionary to get the value from
        keys (str): The keys to get the value from
        default (any): The default value to return if the key does not exist

    Returns:
        any: The value of the key or the default value
    """
    return reduce(
        lambda d, key: d.get(key, default) if isinstance(d, dict) else default,
        keys.split("."),
        dictionary,
    )


def add_to_cache(integration, category, key, value):
    """
    Adds a value to the cache of a specific integration

    :param integration: The integration to add the value to
    :param category: The category to add the value to
    :param key: The key to add the value for. If key is "LIST", the value will be treated as a list item and appended to the list.
    :param value: The value to add to the cache

    :return: None
    """
    try:
        config_all = config_helper.Config().cfg
        if config_all["cache"]["file"]["enabled"]:
            mlog.debug(
                "add_to_cache() - Cache is enabled, saving value '"
                + str(value)
                + "' to cache. Category: '"
                + str(category)
                + "' with key: '"
                + str(key)
                + "' in integration: "
                + integration
            )
            cache_file = config_all["cache"]["file"]["path"]
            with open(cache_file, "r") as f:
                cache = json.load(f)

            if key == "LIST":
                mlog.debug("add_to_cache() - Key is 'LIST' literal, appending value to list")
                try:
                    if value in cache[integration][category]:
                        mlog.debug("add_to_cache() - Value '" + str(value) + "' already exists in cache, skipping")
                        return
                    cache[integration][category].append(value)
                except KeyError:
                    if integration not in cache:
                        cache[integration] = {}
                    if category not in cache[integration]:
                        cache[integration][category] = []

                    cache[integration][category].append(value)
            else:
                try:
                    cache[integration][category][key] = value
                except KeyError:
                    if integration not in cache:
                        cache[integration] = {}
                    if category not in cache[integration]:
                        cache[integration][category] = {}

                    cache[integration][category][key] = value

            with open(cache_file, "w") as f:
                try:
                    json.dump(cache, f)
                except TypeError:
                    json.dump(cache, f, default=str)
            mlog.info(
                "add_to_cache() - Value '"
                + str(value)
                + "' saved to cache. Category: '"
                + category
                + "' with key: '"
                + key
                + "' in integration: "
                + integration
            )
    except Exception as e:
        mlog.warning("add_to_cache() - Error adding value to cache: " + str(e))


def get_from_cache(integration, category, key="LIST"):
    """
    Gets a value from the cache of a specific integration

    :param integration: The integration to get the value from
    :param category: The category to get the value from
    :param key: The key to get the value for. If key is "LIST", the value will be treated as a list and returned.

    :return: The value from the cache
    """
    try:
        config_all = config_helper.Config().cfg
        if config_all["cache"]["file"]["enabled"]:
            mlog.debug(
                "get_from_cache() - Cache is enabled, checking cache for category '"
                + str(category)
                + "' with key: '"
                + str(key)
                + "' in integration: "
                + integration
            )

            # Load cahceh file to variable
            cache_file = config_all["cache"]["file"]["path"]
            mlog.debug("get_from_cache() - Loading cache file: " + cache_file)
            with open(cache_file, "r") as f:
                cache = json.load(f)

            # Check if category just stores a list
            if key == "LIST":
                mlog.debug("get_from_cache() - Category stores a list, returning list")
                try:
                    return cache[integration][category]
                except KeyError:
                    mlog.debug("get_from_cache() - Category does not exist in cache")
                    return None

            # Check if entity is in cache
            entity = dict_get(cache[integration][category], str(key))
            if entity:
                mlog.debug("get_from_cache() - Found entity in cache")
                return entity
            else:
                try:
                    entity = cache[integration][category][key]
                    mlog.debug("get_from_cache() - Found entity in cache")
                    return entity
                except KeyError:
                    mlog.debug("get_from_cache() - Entity not found in cache")
                return None
    except Exception as e:
        mlog.warning("get_from_cache() - Error getting value from cache: " + str(e))
        return None


def del_none_from_dict(d):
    """
    Delete keys with the value ``None`` in a dictionary, recursively.

    This alters the input so you may wish to ``copy`` the dict first.

    Args:
        d (dict): The dictionary to remove the keys from

    Returns:
        dict: The cleaned dictionary
    """
    # For Python 3, write `list(d.items())`; `d.items()` won’t work
    # For Python 2, write `d.items()`; `d.iteritems()` won’t work
    if d is None:
        return None
    if type(d) is int:
        return d
    for key, value in list(d.items()):
        if value is None:
            del d[key]
        elif type(value) is list:
            for item in value:
                if isinstance(item, dict):
                    del_none_from_dict(item)
        elif str(value) == "[]":  # Remove trivial empty strings
            del d[key]
        elif type(value) is str and value in ("", "Unknown", "N/A"):  # Remove trivial empty strings
            del d[key]
        elif isinstance(value, dict):
            del_none_from_dict(value)
    return d  # For convenience


def color_cell(cell):
    try:
        return "color: " + ("red" if int(cell) > 0 else "green")
    except ValueError:
        return "color: black"


def format_results(events, format, group_by="uuid", transform=False):
    if events is None or (type(events) == list and len(events) == 0):
        return "~ No results found ~"
    if type(events) is list and len(events) == 1:
        events = events[0]
    if type(events) is not list:
        events = [events]

    dict_events = []

    # Removing fields that are unnecessary for the table view
    for event in events:
        if event is None or type(event) is int:
            continue
        if type(event) is list:
            event = event[0]
            mlog.warning("format_results() - 'Event' is a list, taking first item")

        event = event.__dict__()
        if "uuid" in event:
            del event["uuid"]
        if "process_parent" in event:
            del event["process_parent"]
        if "process_flow" in event:
            del event["process_flow"]
        if "process_http" in event:
            del event["process_http"]
        if "process_parent_start_time" in event:
            del event["process_parent_start_time"]
        if "process_sha256" in event:
            del event["process_sha256"]
        if "process_sha1" in event:
            del event["process_sha1"]
        if "parent_process_arguments" in event:
            del event["parent_process_arguments"]
        if "process_modules" in event:
            del event["process_modules"]
        if "process_arguments" in event:
            del event["process_arguments"]
        if "process_children" in event:
            del event["process_children"]
        if "related_alert_uuids" in event:
            del event["related_alert_uuids"]
        if "process_uuid" in event:
            del event["process_uuid"]
        if "related_alert_uuid" in event:
            del event["related_alert_uuid"]

        if "process_id" in event and event["process_id"] is not None:
            if type(event["process_id"]) is not int:  # If a UUID == process_id, limit it to not be too long in the table
                event["process_id"] = event["process_id"][:5]

        # Try to expand some fields
        try:
            if "destination_location" in event:
                loc = event["destination_location"]
                del event["destination_location"]

                if loc is not None and loc != "None":
                    loc = json.loads(loc)
                    country = dict_get(loc, "country")
                    if country is not None:
                        event["destination_location_country"] = country

                    city = dict_get(loc, "city")
                    if city is not None:
                        event["destination_location_city"] = city

                    org = dict_get(loc, "org")
                    if org is not None:
                        event["destination_location_org"] = org

            if "dns_query" in event:
                dns_query = event["dns_query"]
                del event["dns_query"]

                if dns_query is not None and dns_query != "None":
                    dns_query = json.loads(dns_query)

                    dns_query = dict_get(dns_query, "query")
                    if dns_query is not None:
                        event["dns_query"] = dns_query

                    dns_query_response = dict_get(dns_query, "query_response")
                    if dns_query_response is not None:
                        event["dns_response"] = dns_query_response

            if "http" in event:
                http = event["http"]
                del event["http"]

                if http is not None and http != "None":
                    http = json.loads(http)

                    http_url = dict_get(http, "full_url")
                    if http_url is not None:
                        event["full_url"] = http_url

                    http_method = dict_get(http, "method")
                    if http_method is not None:
                        event["http_method"] = http_method

                    http_status_code = dict_get(http, "status_code")
                    if http_status_code is not None:
                        event["http_status_code"] = http_status_code

                    http_user_agent = dict_get(http, "user_agent")
                    if http_user_agent is not None:
                        event["http_user_agent"] = http_user_agent

                    http_referer = dict_get(http, "host")
                    if http_referer is not None:
                        event["host"] = http_referer

                    http_body = dict_get(http, "request_headers")
                    if http_body is not None and http_body != "None":
                        event["request_headers"] = http_body

                    http_body = dict_get(http, "request_body")
                    if http_body is not None and http_body != "None":
                        event["request_body"] = http_body

                    http_body = dict_get(http, "response_headers")
                    if http_body is not None and http_body != "None":
                        event["response_headers"] = http_body

                    http_body = dict_get(http, "response_body")
                    if http_body is not None and http_body != "None":
                        event["response_body"] = http_body

                    http_body = dict_get(http, "certificate")
                    if http_body is not None and http_body != "None":
                        event["response_body"] = http_body

            if "device" in event or "log_source_device" in event:
                if "device" in event:
                    device = event["device"]
                    del event["device"]
                if "log_source_device" in event:
                    device = event["log_source_device"]
                    del event["log_source_device"]

                if device is not None and device != "None":
                    device = json.loads(device)

                    device_name = dict_get(device, "name")
                    if device_name is not None:
                        event["device_name"] = device_name

                    device_type = dict_get(device, "type")
                    if device_type is not None and device_type != "None":
                        event["device_type"] = device_type

                    device_os = dict_get(device, "os")
                    if device_os is not None:
                        event["device_os"] = device_os

            if "process_signature" in event:
                signature = event["process_signature"]
                del event["process_signature"]

                if signature is not None and signature != "None":
                    signature = json.loads(signature)

                    issuer = dict_get(signature, "issuer")
                    if issuer is not None:
                        event["process_signature_issuer"] = issuer

                    event["process_signature_trusted"] = dict_get(signature, "is_trusted")

        except Exception as e:
            mlog.warning("format_results() - Error expanding fields: " + str(e))

        # Try to remove undetected / clean ThreatIntel Engine hits, as they are too many to be readable
        try:
            if "threat_intel_alerts" in event:
                alerts_hit = ""
                alerts = event["threat_intel_alerts"]
                del event["threat_intel_alerts"]

                if alerts is not None and alerts != "None":
                    for alert in alerts:
                        if alert.is_hit == True:
                            alerts_hit += "[ '" + alert.engine + "': " + alert.threat_name + " ]  "

                event["threat_intel_alerts"] = alerts_hit
        except Exception as e:
            mlog.warning("format_results() - Error removing clean ThreatIntel Engine hits: " + str(e))

        event = del_none_from_dict(event)
        dict_events.append(event)

    # If only one event, return it as a dict
    if len(dict_events) == 1:
        dict_events = dict_events[0]

    # events = [del_none_from_dict(event.__dict__()) for event in events]

    if format in ("html", "markdown"):
        if type(dict_events) is list and len(dict_events) > 0:
            data = pd.DataFrame(data=dict_events)
            if group_by != "":
                data = data.groupby([group_by]).agg(lambda x: x.tolist())
            data.dropna(axis=1, how="all", inplace=True)
        else:
            data = pd.DataFrame.from_dict(dict_events, orient="index")
            data = data.T

        # TODO: Add color support

        if transform:
            data = data.T

        if format == "html":
            tmp = data.to_html(index=False, classes=None, bold_rows=True)
            return tmp.replace(' class="dataframe"', "")

        elif format == "markdown":
            return data.to_markdown(index="false")
    elif format == "json":
        return json.dumps(events, ensure_ascii=False, sort_keys=False)


def get_unique(data):
    """Get unique values from a list"""
    return list(set(data))


# [internal note] Copied the following from class_helper to this file, to better separate classes and generic functions


def cast_to_ipaddress(ip, strict=True) -> Union[ipaddress.IPv4Address, ipaddress.IPv6Address]:
    """Tries to cast a string to an IP address.

    Args:
        ip: The IP address to cast

    Returns:
        ipaddress.IPv4Address or ipaddress.IPv6Address: The IP address object

    Raises:
        ValueError: If the IP address is invalid
    """
    if not ip and not strict:
        return None
    if type(ip) != ipaddress.IPv4Address and type(ip) != ipaddress.IPv6Address and type(ip) != None:
        try:
            ip = ipaddress.ip_address(ip)
        except ValueError:
            if strict:
                raise ValueError("invalid ip address: " + str(ip))
            else:
                return None
    return ip


def handle_percentage(percentage):
    """Handles a percentage value.

    Args:
        percentage (int): The percentage value

    Returns:
        int: The percentage value

    Raises:
        TypeError: If the percentage value is not an integer
        ValueError: If the percentage value is higher than 100 or lower than 0
    """
    if percentage is None:
        return None
    if type(percentage) != int:
        raise TypeError("Percentage value must be an integer")
    if percentage > 100:
        raise ValueError("Percentage value cannot be higher than 100")
    if percentage < 0:
        raise ValueError("Percentage value cannot be lower than 0")
    return percentage


def add_to_timeline(context_list, context, timestamp: datetime):
    """Adds a context to a context list, respecting the timeline.

    Args:
        context_list (list): The context list
        context (dict): The context to add
        timestamp (datetime): The timestamp of the context

    Returns:
        None
    """
    if type(context) == list and len(context) >= THRESHOLD_MAX_CONTEXTS:
        mlog = logging_helper.Log("lib.class_helper")
        mlog.debug(
            "add_to_timeline() - [OVERFLOW PROTECTION] Maximum number of contexts reached. No more contexts will be added to the context list of context type '"
            + str(type(context_list[0]))
            + "'."
        )  # This logs to debug instead of warning, as it can likely spam the log and also there should be a warning on playbook level
        return

    if len(context_list) == 0:
        context_list.append(context)
    else:
        for i in range(len(context_list)):
            if context_list[i].timestamp > timestamp:
                context_list.insert(i, context)
                break
            elif i == len(context_list) - 1:
                context_list.append(context)
                break


def remove_duplicates_from_dict(d):
    """Removes duplicate values from a dictionary.

    Args:
        d (dict): The dictionary to remove the duplicates from

    Returns:
        dict: The dictionary without duplicates
    """
    if d is None:
        return None
    for key, value in list(d.items()):
        if type(value) is list:
            d[key] = list(dict.fromkeys(value))
        elif isinstance(value, dict):
            remove_duplicates_from_dict(value)
    return d  # For convenience


def is_local_tld(domain):
    """Checks whether a domain has a local (private) TLD."""
    domain = domain.lower()  # Convert to lower case
    local_tlds = [".local", ".localdomain", ".domain", ".lan", ".home", ".host", ".corp"]
    return any(domain.endswith(tld) for tld in local_tlds)


def default(obj):
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    raise TypeError


import re
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode


def redact_url(url: str) -> str:
    """
    Redacts sensitive information from a URL.

    Parameters:
        url (str): The URL to redact.

    Returns:
        str: The redacted URL.
    """
    SENSITIVE_PARAMS = ["password", "token", "apikey", "secret"]

    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)

    # Redact sensitive parameters
    for param in SENSITIVE_PARAMS:
        if param in query_params:
            query_params[param] = ["REDACTED"]

    redacted_query = urlencode(query_params, doseq=True)

    # Construct redacted URL
    redacted_url = urlunparse(
        (parsed_url.scheme, parsed_url.netloc, parsed_url.path, parsed_url.params, redacted_query, parsed_url.fragment)
    )
    return redacted_url


def redact_string(s):
    """Redacts a string by replacing passwords, tokens, etc. with asterisks."""
    s = str(s)
    # First try to redact string if its an url:
    try:
        s_new = redact_url(s)
    except Exception as e:
        pass

    if s_new != s:
        mlog.info("redact_string() - Redacted string '" + s + "' to '" + s_new + "'")

    return s


def make_json_serializable(obj):
    """Converts all datetime and UUID objects in a nested structure to strings.

    Args:
        obj (dict/list): The dictionary or list to process.

    Returns:
        dict/list: The processed dictionary or list.
    """

    queue = deque([obj])

    while queue:
        current = queue.popleft()

        if isinstance(current, dict):
            for k, v in current.items():
                if isinstance(v, datetime.datetime):
                    current[k] = v.isoformat()
                elif isinstance(v, UUID):
                    current[k] = str(v)
                elif isinstance(v, (list, dict)):
                    queue.append(v)
        elif isinstance(current, list):
            for i, v in enumerate(current):
                if isinstance(v, datetime.datetime):
                    current[i] = v.isoformat()
                elif isinstance(v, UUID):
                    current[i] = str(v)
                elif isinstance(v, (list, dict)):
                    queue.append(v)

    return obj
