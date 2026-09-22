import type { MessageKey, PluralKey } from "./ru";

export const en: Record<MessageKey, string> = {
  "common.retry": "Retry",
  "common.cancel": "Cancel",
  "common.close": "Close",
  "common.copy": "Copy",
  "common.copied": "Copied",
  "common.loading": "Loading…",
  "common.done": "Done",
  "common.back": "Back",

  "error.title": "Something went wrong",
  "error.network": "No connection to the server. Check your internet.",
  "error.unauthorized": "Open the app from Telegram.",
  "error.initdata_expired": "Session expired. Close and reopen the app.",
  "error.rate_limited": "Too many requests. Wait a minute.",
  "error.device_limit_reached": "Device limit reached for your plan.",
  "error.trial_already_used": "The trial period has already been used.",
  "error.subscription_inactive": "Subscription is not active.",
  "error.node_unavailable": "The server is temporarily unavailable. Try later.",
  "error.not_found": "Not found.",
  "error.internal": "Internal server error.",
  "error.code": "Code",
  "error.support": "Contact support",

  "nav.subscription": "Subscription",
  "nav.devices": "Devices",
  "nav.plans": "Plans",
  "nav.more": "More",

  "title.home": "My subscription",
  "title.plans": "Plans",
  "title.checkout": "Payment",
  "title.devices": "Devices",
  "title.deviceNew": "New device",
  "title.deviceKey": "Connection key",
  "title.deviceGuide": "Setup",
  "title.renew": "Renewal",
  "title.account": "Account",
  "title.onboarding": "ocmanager",
  "title.error": "Error",

  "plans.title": "Plans",
  "plans.subtitle": "Pick the one that fits",
  "plans.buy": "Buy for {price}",
  "plans.current": "Current plan",
  "plans.currentShort": "CURRENT",
  "plans.unlimitedTraffic": "Unlimited traffic",
  "plans.trafficPerMonth": "{amount} per month",
  "plans.trialTitle": "Try for free",
  "plans.trialBody": "{days} and {traffic} — no payment, no card",
  "plans.trialStart": "Start free trial",
  "plans.trialUsed": "Trial already used",
  "plans.empty": "No plans configured yet",

  "subscription.title": "Subscription",
  "subscription.none": "No subscription",
  "subscription.noneBody": "Pick a plan to start using the VPN",
  "subscription.choosePlan": "Choose a plan",
  "subscription.expiresOn": "Valid until {date}",
  "subscription.expiredOn": "Ended on {date}",
  "subscription.autoRenewOn": "Renews automatically",
  "subscription.autoRenewOff": "Auto-renewal is off",
  "subscription.traffic": "Traffic",
  "subscription.trafficUsed": "{used} of {limit}",
  "subscription.trafficUnlimited": "Unlimited",
  "subscription.trafficResets": "Resets on {date}",
  "subscription.devicesUsed": "Devices: {used} of {limit}",
  "subscription.extend": "Extend",
  "subscription.renew": "Resume",

  "status.trial": "Trial",
  "status.active": "Active",
  "status.expired": "Expired",
  "status.exhausted": "Traffic used up",
  "status.cancelled": "Active until period ends",
  "status.blocked": "Blocked",
  "status.pending_payment": "Awaiting payment",

  "devices.title": "Devices",
  "devices.add": "Add device",
  "devices.empty": "No devices yet",
  "devices.emptyBody": "Add a device to get a connection key",
  "devices.online": "Connected",
  "devices.lastSeen": "Last seen {when}",
  "devices.neverConnected": "Never connected",
  "devices.revoke": "Revoke",
  "devices.revokeTitle": "Revoke this device?",
  "devices.revokeBody":
    'The key "{name}" will stop working immediately and cannot be restored.',
  "devices.revoked": "Device revoked",
  "devices.limitReached": "Plan device limit reached",
  "devices.instructions": "Setup guide",
  "devices.slots": "{used} of {limit} in use",
  "devices.freeSlot": "Free slot",
  "devices.freeSlotBody": "Issue a key for a new device",
  "devices.revokeConfirm": "Revoke device",
  "devices.note":
    "One key works on one device. A revoked key stops connecting immediately and frees its slot.",

  "deviceCreate.title": "New device",
  "deviceCreate.pickPlatform": "Choose the operating system",
  "deviceCreate.name": "Name",
  "deviceCreate.namePlaceholder": "Ivan's iPhone",
  "deviceCreate.submit": "Issue key",
  "deviceCreate.issuing": "Issuing the key…",
  "deviceCreate.intro":
    "Pick the device's operating system — it decides the key format and the setup guide.",
  "devices.manage": "Back to devices",

  "deviceSecret.title": "Your key is ready",
  "deviceSecret.warning":
    "The password and the link are shown once. Download the file now — it cannot be restored.",
  "deviceSecret.password": "File password",
  "deviceSecret.download": "Download key",
  "deviceSecret.expiresIn": "The link is valid for {time} more",
  "deviceSecret.expired": "The link has expired. Issue a new device.",
  "deviceSecret.qrHint": "Scan to open on your phone",
  "deviceSecret.next": "Go to the setup guide",

  "instructions.title": "How to connect",
  "instructions.step": "Step {n}",
  "instructions.server": "Server address",
  "instructions.openStore": "Open in the app store",

  "checkout.total": "Total",
  "checkout.plan": "Plan",
  "checkout.period": "Period",
  "checkout.method": "Payment method",
  "checkout.autoRenew": "Auto-renewal",
  "checkout.autoRenewOn": "will be enabled",
  "checkout.pay": "Go to payment",
  "checkout.opening": "Opening payment…",
  "checkout.note":
    "Payment opens in Tribute. The app will close — the bot will message you in the chat once access is ready. It usually takes a few seconds.",
  "checkout.hint":
    "After paying, come back to Telegram — the bot will message you once the subscription is active.",
  "checkout.notFound": "Plan not found",
  "checkout.notFoundBody": "It may no longer be on sale. Pick another one.",

  "subscription.autoRenew": "Auto-renewal",
  "subscription.nextCharge": "Charges {price}",
  "subscription.on": "on",
  "subscription.off": "off",
  "subscription.accessLeft": "Access active for",
  "subscription.changePlan": "Change plan",
  "subscription.changePlanBody": "More devices or traffic",

  "instructions.ios.1": "Install Cisco Secure Client from the App Store",
  "instructions.ios.2":
    "Open the downloaded key file and enter the password — iOS will offer to install a profile",
  "instructions.ios.3":
    "Settings → General → VPN & Device Management → install the profile",
  "instructions.ios.4":
    "Open Cisco Secure Client, add a connection with the server address and turn the VPN on",

  "instructions.android.1": "Install Cisco Secure Client from Google Play",
  "instructions.android.2":
    "In the app open Menu → Manage certificates → Import from file",
  "instructions.android.3":
    "Pick the downloaded key file and enter the password",
  "instructions.android.4":
    "Add a connection with the server address, select the imported certificate and turn the VPN on",

  "instructions.windows.1": "Install OpenConnect GUI from the official site",
  "instructions.windows.2":
    "Double-click the downloaded key file and enter the password — Windows stores the certificate in your personal store",
  "instructions.windows.3":
    "In OpenConnect GUI create a profile, enter the server address and pick the certificate from the store",
  "instructions.windows.4":
    "Press Connect — the tunnel comes up in a couple of seconds",

  "instructions.macos.1": "Install OpenConnect GUI or Cisco Secure Client",
  "instructions.macos.2":
    "Double-click the downloaded key file and enter the password — the certificate goes into Keychain",
  "instructions.macos.3":
    "Create a profile with the server address and select the imported certificate",
  "instructions.macos.4":
    "Connect and allow the system to add the VPN configuration",

  "instructions.linux.1":
    "Install the openconnect package: apt install openconnect or dnf install openconnect",
  "instructions.linux.2":
    "Unpack the key: openssl pkcs12 -in key.p12 -out key.pem -nodes (it asks for the password)",
  "instructions.linux.3":
    "Connect: sudo openconnect --certificate=key.pem <server address>",
  "instructions.linux.4":
    "For a persistent connection add a NetworkManager profile: nmcli connection add type vpn",

  "renew.nextCharge": "Next charge",
  "renew.price": "Renewal price",
  "renew.accessEnds": "Access ends on {date}",
  "renew.managed":
    "Turned on and off in Tribute — where the payment was set up",
  "renew.note":
    "Renewal only moves the date: keys are not reissued, the connection is not dropped, and the traffic counter starts over. Turning auto-renewal off does not cut access — the paid period runs to its end.",
  "renew.submit": "Renew now for {days}",

  "account.language": "Language",
  "account.theme": "Theme",
  "account.themeSystem": "Match Telegram",
  "account.themeLight": "Light",
  "account.themeDark": "Dark",
  "account.support": "Support",
};

export const enPlural: Record<
  PluralKey,
  { one: string; few: string; many: string; other: string }
> = {
  "unit.day": {
    one: "{n} day",
    few: "{n} days",
    many: "{n} days",
    other: "{n} days",
  },
  "unit.dayBare": {
    one: "day",
    few: "days",
    many: "days",
    other: "days",
  },
  "unit.device": {
    one: "{n} device",
    few: "{n} devices",
    many: "{n} devices",
    other: "{n} devices",
  },
  "unit.dayLeft": {
    one: "{n} day left",
    few: "{n} days left",
    many: "{n} days left",
    other: "{n} days left",
  },
};
