# Changelog

All notable, community-facing changes to ImperialReminder are recorded here in plain language.
For the technical, commit-level history, see git.

## [Unreleased] - 2026-08-26 (readable dashboard errors)

### Fixed
- **Dashboard error messages for invalid form input are readable now.** Some validation
  errors used to render as raw data instead of a sentence naming the field and the problem.

### Changed
- **Picking a Bump Role that cannot actually be pinged is now refused.** Choosing @everyone,
  a bot's own role, or a role with mentions turned off used to save without complaint and
  then produce reminders that pinged nobody - the role name showed up as plain text and no
  one was notified. The panel now explains why the pick will not work (and, for a role with
  mentions turned off, tells you to switch on "Allow anyone to @mention this role" in the
  role's settings) so you can fix it straight away instead of finding out the next time a
  bump was missed.

## [Unreleased] - 2026-08-24 (Imperial Reminder is now 100% free)

### Changed
- **Every feature is now free for every server.** Custom reminder wording and the shorter
  waits on OneBump (30 minutes) and Unfocused (90 minutes) no longer need premium - write
  your message, pick your cooldown, and it is used. There is no premium tier any more: the
  `/premium` commands are gone, the Premium sections have left the admin panel and the
  dashboard, and nothing is locked behind a grant.
- **The privacy policy and terms were updated to match.** The bot no longer keeps premium
  records of any kind, and the policy no longer mentions them.

## [Unreleased] - 2026-08-24 (picking a channel checks everything the bot needs)

### Fixed
- **Your data from a server you have left can be exported and erased again.** The privacy
  page has always listed such servers in its picker (shown without a name), because your
  stored records outlive your membership - but choosing one then failed with "not a member",
  so the download and delete buttons never worked for exactly those rows. They do now;
  servers where you have no data still refuse as before.

### Changed
- **Choosing a Bump Channel or Timers Channel in the admin panel now checks every permission
  the bot really needs there.** Besides sending messages and embeds, the bot has to read the
  channel's message history - that is how it catches bump bots that edit their message just
  after posting (WeBump does this), and how it clears the old countdown embed instead of
  leaving stale ones piling up. Before, picking a channel where history reading was blocked
  looked fine and those features quietly stopped working; now the panel names the exact
  missing permission the moment you pick the channel, so you can fix it right away.

## [Unreleased] - 2026-08-22 (admin panel pickers)

### Changed
- **A refused pick in the admin panel no longer stays selected.** When a channel, role or
  option is turned down (wrong permissions, a role the bot cannot manage, an invalid choice),
  the picker now resets to what is actually saved, so you can pick again straight away instead
  of having to choose something else first.
- **Creating a role from the admin panel now reminds you where it landed.** Discord puts a new
  role at the bottom of the role list; the confirmation says so and points you to Server
  Settings -> Roles if it needs to sit higher.

## [Unreleased] - 2026-08-19 (where premium is explained)

### Fixed
- **Pressing Escape no longer closes a confirmation box while the action is already running.**
  When you confirm something destructive, the Cancel button greys out and clicking outside the
  box does nothing, because by then there is nothing left to call off. Escape ignored that and
  closed the box anyway, so the action carried on out of sight and it looked like you had
  stopped it. Escape now behaves like the other two, and still closes the box normally before
  you confirm.

### Changed
- **The Premium page in `/help` is now shown to server admins rather than everyone.** Premium
  applies to a whole server and is arranged by whoever runs it, so its write-up sits with the
  admin pages now. Nothing about the `/premium status` command has changed - anyone can still
  run it, and the answer is still only visible to the person who ran it.

## [Unreleased] - 2026-08-17 (bump reminder check)

### Fixed
- **The page now tells you straight when you are not on the bump reminder list.** If you held no
  roles at all, the check said "we could not confirm" rather than simply "no" - it could not tell
  the difference between having no roles and not being able to reach Discord. It can now, so you
  get a real answer, and "we could not confirm" appears only when that is genuinely the case.

## [Unreleased] - 2026-08-17 (dashboard charts and sign-in)

### Fixed
- **Dates under the bar charts no longer overlap.** On a narrow screen, or when a chart covered a
  lot of days, the labels along the bottom could print on top of one another and become
  unreadable. The chart now shows as many labels as genuinely fit the space, and always keeps the
  first and the last so you can see the range at a glance.
- **A brief Discord outage no longer keeps you locked out of the dashboard for a full minute.**
  When Discord could not be reached to confirm your roles, the dashboard remembered that failure
  for 60 seconds, so you stayed shut out even after Discord had come back. It now tries again
  within about 10 seconds.
- **The same applies to a server admin.** The check that confirms you manage this server had the
  same problem and it locked out harder: one failed reply shut every admin of that server out for
  a full minute. It now retries after about ten seconds.
- **The dashboard no longer creeps up in memory the longer it runs.** Two internal lookup caches
  never cleared out entries that had gone stale.

## [Unreleased] - 2026-08-17

### Fixed
- **Buttons that are switched off no longer light up when you point at them.** A greyed-out
  button on the dashboard still glowed as though you could press it, which made it look
  available when it was not. It now stays quiet until it is actually usable.

## [Unreleased] - 2026-08-15

### Changed
- **What people say in the bump channel no longer goes into our logs.** Every message posted in a
  server's bump channel had its full text written to the bot's running log, including ordinary
  conversation that had nothing to do with bumping. The log now records only that a message was
  checked and whether it came from a bump bot. The wording itself is kept only when detailed
  troubleshooting is switched on deliberately.

### Fixed
- **Reminders work in servers invited from the website.** The invite link the dashboard builds was
  missing permission to read message history, which the bot needs to re-read a bump message after
  a bump bot edits it and to tidy up its own old timer messages. In a server added that way,
  detection could fail silently and no reminder would ever arrive. Servers already invited are
  unaffected.
- **The admin panel no longer fails to open a menu when a summary line gets long.** If a
  dropdown entry's summary grew past what Discord allows - for example a setting listing
  many roles or channels - the whole screen failed with an error instead of showing. Long summaries now switch to a
  compact form such as "12 roles assigned" - the full list still appears in the text right
  above - and the menu always opens. Also, a few settings descriptions on the main panel screen
  were tightened so they display in full instead of being cut off mid-sentence.

## [Unreleased] - 2026-08-13

### Added
- **Everyone in your server can use the dashboard now, not just its managers.** Sign in and any
  server you share with the bot appears, opening on a page that answers the question a member
  actually has: when is the next bump due, and **will I be pinged for it?** If you hold the
  server's reminder role it says so; if you do not, it says that too, and if we cannot check your
  roles at that moment it says we could not check rather than guessing. Members see timings and
  status only - never the server's channels, roles or setup.
- **"What you can use" on every server page.** A plain-language summary of what the server
  unlocks: whether it has premium, whether its reminders use custom wording or the standard one,
  which listing services allow a shorter wait and whether that is switched on, and the two
  commands anyone can run.
- **Server managers see their own reminders first.** If you manage a server, your personal
  section is at the top of the page and the server overview follows underneath. You are a member
  of your server before you are its administrator.
- **A Change history page.** Settings, then Change history, shows every setting anyone has
  changed in your server: who changed it, whether they used Discord or the dashboard, what it was
  and what it became. Older changes load on demand, and entries are kept for a year.
- **Changes made on the dashboard are now recorded.** Until now only edits made from the
  in-Discord panel appeared in a server's history, so anything changed on the web was invisible.
  Both are recorded the same way, which also means the web edits show up in your personal data
  export.
- **Per-bot cooldowns moved onto the dashboard.** A new Cooldowns section lets you set how long
  the bot waits before saying a service can be bumped again. Services with a single fixed cooldown
  are listed as fixed rather than given a pointless dropdown, and a shorter premium-only wait
  cannot be picked on a server without premium - it is refused with a reason instead of being
  quietly ignored.
- **A Terms of Service page**, linked from the footer of every page alongside the privacy policy.
- **The login page now says how the bot is actually being used**: how many servers are fully set
  up, and how many servers are watching each listing service.

### Fixed
- On phones, the server panel on the settings hub now shows its close button and its server
  icon in full instead of cutting them off at the panel's rounded edge, and the close button
  stays put while you scroll the panel.

### Changed
- **The dashboard has been rebuilt around one question: is it working?** Opening a server now
  starts with a row of feature cards - bump watching, reminder pings, the live countdown, your
  custom message and who can manage the bot - each saying On, Off, or Needs setup with the reason.
  Underneath it are the bump timers you already had, plus what is set up, your premium status and
  a record of recent setting changes with a 30-day chart. The old strip of server buttons is now a
  search-friendly server picker, and the page finally has a sensible maximum width, so on a big
  monitor the cards no longer stretch across the whole screen.
- **The dashboard tells you when your custom reminder is not actually being sent.** A custom
  reminder message needs premium. If your server has written one without premium, the dashboard
  now says so plainly instead of showing it as configured while the standard reminder goes out.
- **The settings page is now a list of sections instead of one long form.** Bumping, bump bots,
  cooldowns, the live countdown, the reminder wording and who can manage each have their own page,
  with a search box, a badge showing what still needs setting up, and a panel beside the form
  showing what that setting is doing right now.
- **Each settings section now saves on its own.** Changing your reminder role no longer rewrites
  your custom message, your bot list and your manager roles along with it. Every section has its
  own Save button, a section with unsaved edits is marked **Unsaved** in the list, your edits
  still survive moving between sections, and moving away from a section you have not saved asks
  first instead of letting you lose it quietly.
- **The privacy page now shows what is actually held about you.** It counts the records that name
  your account - for one server or all of them - before you decide whether to download or erase
  them, spells out exactly what the download contains, and says plainly what stays behind after an
  erasure and why: the record that a setting changed belongs to the server, so erasing removes
  your name and ID from it rather than deleting the server's history.
- **The privacy policy has been corrected and expanded.** It no longer mentions premium redemption
  codes, which the bot no longer has; it now describes the settings-change records and how long
  they are kept, and it explains erasure-by-redaction and links to the self-service page.
- **Everything reads properly on a phone.** The dashboard, settings and the Web of Servers all
  collapse to a single column on a narrow screen instead of squeezing content off the side, and
  the header no longer overlaps itself.
- **The Web of Servers is now a living web.** The server picker page is a full-screen scene of
  your servers woven together with silk strands: pick a node and its options grow out of the web
  towards it. On a phone those options slide up from the bottom of the screen instead. Servers
  the bot has not been set up in are marked, and servers it has not been added to are dimmed with
  an invite button.

## [Unreleased] - 2026-08-07

### Added
- **There is now an About page explaining the whole project.** The dashboard's login page and
  the footer on every page link to a new About page for Empire of Shadows: what each of the six
  bots does, how they fit together, and why the project is built as separate bots instead of one
  big one. Handy if you have just found one of the bots and want to know what the rest of it is.

## [Unreleased] - 2026-08-06

### Changed
- **The separate moderator access level is gone.** Imperial Reminder used to have two kinds of
  access: admin roles that could change settings, and mod roles that could look at them without
  changing anything. There is now only one. The admin panel and the web dashboard both require
  the Manage Server permission or a role listed under **Panel Access Roles** - anyone else cannot
  open them, view them, or change anything. If your server relied on mod roles for a read-only
  look at the settings, add those roles to Panel Access Roles to give them full access, or leave
  them out.
- **Panel Access Roles is now its own entry on the admin panel.** With the mod picker gone there
  was only one setting left inside the old **Panel Access** menu, so it moved up to the panel's
  front screen next to Core Setup - one click instead of two.

## [Unreleased] - 2026-08-05

### Added
- **Create roles and channels straight from the picker.** Every role and channel picker in the
  admin panel now carries a Create button: type a name and the new role or channel is created and
  selected in one step, without leaving the panel. The button first checks that the bot itself is
  allowed to create it and tells you which permission is missing instead of failing afterwards.
  Text channel names follow Discord's rules (lowercase letters, digits and dashes), and a rejected
  name comes back with a Try Again button that keeps what you typed.
- **Pick a category when creating a channel.** The Create Channel button in the admin panel now
  lets you choose which category the new channel goes under - or leave the picker empty to create
  it at the top of the channel list. If something goes wrong, Try Again keeps both the name you
  typed and the category you picked.

### Changed
- **The panel now refuses roles that would not actually work.** The pickers that decide who can
  open the admin panel no longer accept @everyone or roles managed by an integration (bot roles,
  booster roles) - membership of those is outside the server's control, so allowing them would
  open the panel wider than intended. Regular admin roles still work, including ones that sit
  above the bot. Every refusal explains itself.

## [Unreleased] - 2026-08-02

### Added
- **There is now a `/help` command.** Imperial Reminder mostly works in the background, which
  made it hard to tell what it was doing or whether it was doing anything at all. `/help` opens a
  short guide you can page through with a dropdown: what the bot does, how a bump turns into a
  countdown and then into a ping, which listing sites it can watch, and what premium adds. Only
  you can see it, and there is a button straight to the web dashboard.
- Server admins see an extra **Admin** section in that guide covering `/admin panel`, what each
  part of the panel is for, and the two settings - a bump channel and a bump role - that have to
  be set before any reminders run.

## [Unreleased] - 2026-08-01

### Fixed
- **The privacy policy said the bot does not read your messages. That was not true.** Imperial
  Reminder has to read messages in your bump channel - that is the only way it can spot a bump
  bot's "bump done" message and start the timer. It reads nothing outside that one channel, it
  never puts that text in its database, and it still does not track individual members. The policy
  now says exactly that instead of claiming the bot reads nothing, and it also notes that the text
  it reads shows up in the operational log used for troubleshooting.

### Changed
- **The policy you agree to when you sign in now covers every Empire of Shadows service.** One
  login signs you in to all of the bot dashboards, but the login screen only ever pointed at
  Imperial Reminder's own privacy policy, which does not describe what the other bots do with
  your data. Signing in now points you to a single combined Empire of Shadows privacy policy
  covering every bot, dashboard and tool. Imperial Reminder's own privacy page has not gone
  anywhere - it is linked from the same line and from the footer, and still holds the detail
  specific to this bot.

## [Unreleased] - 2026-07-27

### Added
- **The bot now speaks up when it has not been set up.** Until today, a server that added
  Imperial Reminder but never picked a bump channel got complete silence - people would bump,
  nothing would happen, and there was no message, no error and nothing to explain why. Now, when
  a bump goes through on a server that has not finished setup, the bot posts once to say it saw
  the bump, that no reminder was scheduled, and exactly where to fix it: `/admin panel` ->
  **Core Setup**.
- That message also says **who** can fix it. On a server that has not handed out panel access
  yet, only the owner and people with Manage Server can open the panel, so the message names the
  owner rather than telling everyone else to run a command they cannot use - and points the owner
  at **Panel Access** so they can let their staff help.
- It cannot become nagging. The notice appears at most once per day per server, only after a real
  bump from a bump bot the bot recognises (a message that merely says "bump done" can never
  trigger it), and it stays quiet if it lacks permission to post in that channel. Once a bump
  channel is set, it never appears again.

## [Unreleased] - 2026-07-26

### Fixed
- The `/admin` panel's setup progress was counting things you cannot actually configure. Screens
  and buttons that only show information or run an action - such as the premium **Status** view -
  were being added to each category's "X of Y configured" total, so a category could never read
  as finished no matter how much you set up. Only real settings count now, and a category that
  holds nothing but action screens just shows its name instead of a meaningless total.
- A list you had not put anything in yet was being counted as configured. An empty list now
  correctly reads as still needing setup.

## [Unreleased] - 2026-07-23

### Added
- The dashboard's Privacy page is now a real account-control page, matching the one on TheHost.
  You can pick whether to work across all your servers or just one, download a JSON copy of
  everything the bot holds against your Discord account, and erase yourself from it. Imperial
  Reminder still tracks servers rather than members, so what that covers is the audit entries
  written when you change a server's settings, plus any premium grants involving your account.
  Erasing strips your name and Discord ID from those entries while leaving the server's record
  that a setting changed - admins keep their history, and it no longer points at you.

- The Settings home page is now the same "Web of Servers" view the Codex and Host dashboards use:
  your servers are drawn as a live network around the Empire sigil, colour-coded by whether you
  are an admin or a mod there, with a side panel that opens settings for whichever one you pick.
  Servers the bot has not joined yet show an invite link instead.

### Fixed
- Restarting the bot no longer re-pings your bump role. Previously, any cooldown that had already
  run out got announced again every time the bot restarted or reconnected to Discord, so a quiet
  server could be pinged repeatedly for the same bump. The bot now remembers which bump it has
  already reminded you about: a reminder that was missed because the bot was offline still arrives,
  but only once.
- The dashboard's public stats endpoint crashed on every request, so the sign-in page showed no
  server or bump-bot counts.

### Changed
- The dashboard now keeps a readable activity log. Every settings change, sign-in and rejected
  request is recorded with who did it, which server it was for, whether it worked and how long
  it took - so an admin can look back and see what happened. Ordinary page loads stay out of the
  log unless you ask for them (set `DASHBOARD_LOG_READS=1`).
- The dashboard had been running with debug logging left on, which buried anything useful under
  a constant stream of internal chatter. It now logs at the normal level, to both the console and
  a rotating file under `logs/`. Set `LOG_LEVEL=DEBUG` if you ever need the extra detail back.
