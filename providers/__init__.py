"""Discovery of counter sources.

Every `*.py` in this directory (except `_*` and this file) is imported, and
each `Provider` subclass defined in it with a non-empty `id` is registered.
Modules that define none (base.py, youtube.py) are shared code. A file that
fails to import never takes the others down: the failure lands in
LOAD_ERRORS, `doctor` prints it, and `fetch` still reports every other
counter.

Registry order is each provider's `order`, then file name. It decides the
order `types` lists and the order the wizard offers when one link fits
several types (a repository: stars before issues, pull requests and cloners,
so the keyless favourite is preselected).
"""

import importlib.util
import os
import sys

from providers.base import Credential, Provider

PROVIDERS_DIR = os.path.dirname(os.path.abspath(__file__))
LOAD_ERRORS = []


def load_from(directory, package="providers"):
    """Registry {id: provider instance} from every module in `directory`."""
    found = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".py") or name.startswith("_"):
            continue
        modname = package + "." + name[:-3]
        try:
            module = sys.modules.get(modname)
            if module is None:
                spec = importlib.util.spec_from_file_location(modname, os.path.join(directory, name))
                module = importlib.util.module_from_spec(spec)
                sys.modules[modname] = module
                try:
                    spec.loader.exec_module(module)
                except BaseException:
                    sys.modules.pop(modname, None)
                    raise
        except Exception as error:
            LOAD_ERRORS.append((name, "%s: %s" % (type(error).__name__, error)))
            continue
        for obj in list(vars(module).values()):
            if not (isinstance(obj, type) and issubclass(obj, Provider) and obj is not Provider):
                continue
            if obj.__module__ != modname or not obj.id:
                continue
            found.append((int(getattr(obj, "order", 100) or 100), name, obj))
    registry = {}
    for _order, name, obj in sorted(found, key=lambda entry: (entry[0], entry[1])):
        if obj.id in registry:
            LOAD_ERRORS.append((name, "duplicate id %s" % obj.id))
            continue
        registry[obj.id] = obj()
    return registry


def load():
    return load_from(PROVIDERS_DIR)


def credentials_of(providers):
    """{credential id: Credential} over a registry. Two different objects
    claiming one id is a mistake worth surfacing, not silently merging."""
    credentials = {}
    for provider in providers.values():
        cred = provider.credential
        if cred is None:
            continue
        if not isinstance(cred, Credential):
            LOAD_ERRORS.append((provider.id, "credential is not a Credential"))
            continue
        existing = credentials.get(cred.id)
        if existing is not None and existing is not cred:
            LOAD_ERRORS.append((provider.id, "credential id %r defined twice" % cred.id))
            continue
        credentials[cred.id] = cred
    return credentials


def users_of(providers, counters, credential_id):
    """How many configured counters rely on a credential."""
    return sum(1 for c in counters
               if isinstance(c, dict)
               and providers.get(str(c.get("type", ""))) is not None
               and providers[str(c.get("type", ""))].credential is not None
               and providers[str(c.get("type", ""))].credential.id == credential_id)
