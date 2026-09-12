"""Connected accounts (C5): signing in, and reading what an account holds.

Google first, as the person chose: Gmail and Google Calendar, read only. Every
request goes through `akira.core.net.call`, held to the account's own
permission; the lasting sign-in is sealed with DPAPI and never reaches a model.
"""

from .google import (CALENDAR, MAIL, SERVICES, Account, AccountStore, ConnectError,
                     GoogleAccounts, address_of, read_client_file, sign_in)

__all__ = ["CALENDAR", "MAIL", "SERVICES", "Account", "AccountStore", "ConnectError",
           "GoogleAccounts", "address_of", "read_client_file", "sign_in"]
