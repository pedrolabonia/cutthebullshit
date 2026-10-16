-- Close modal dialogs of one app (crash recovery, autosave, scratch disk warnings, error alerts) so it can be
-- scripted again.
--   osascript dismiss_dialogs.applescript "<process name>" [force]  ->  "window -> button" for each one closed
-- Looks in sheets and small windows (alerts), including buttons nested in groups, and clicks the
-- first safe button it finds. With "force", if nothing was clicked it brings the app to the front and presses
-- Return (an app that stopped answering almost always has a modal dialog up; Return = its default button).
-- Needs Accessibility permission for the app that runs it (System Settings > Privacy & Security > Accessibility).
on run argv
	set pname to item 1 of argv
	set force to ((count of argv) > 1)
	set out to {}
	set prefs to {"OK", "Continue", "Don't Send", "Don’t Send", "Not Now", "Don't Recover", "Don’t Recover", "Skip", "Ignore", "No", "Don't Save", "Don’t Save"}
	tell application "System Events"
		if not (exists process pname) then return ""
		tell process pname
			set targets to {}
			repeat with w in (every window)
				try
					repeat with sh in (every sheet of w)
						set end of targets to sh
					end repeat
				end try
				set sr to ""
				try
					set sr to subrole of w
				end try
				set small to false
				try
					set {ww, hh} to size of w
					if ww < 1400 and hh < 1000 then set small to true
				end try
				if small then set end of targets to w -- alerts are small; main windows are not
			end repeat
			repeat with t in targets
				set tname to ""
				try
					set tname to name of t as text
				end try
				set btns to {}
				try
					repeat with e in (entire contents of t)
						try
							if class of e is button then set end of btns to e
						end try
					end repeat
				end try
				set done to false
				repeat with pref in prefs
					repeat with b in btns
						set bname to ""
						try
							set bname to name of b as text
						end try
						if bname is "" then
							try
								set bname to title of b as text
							end try
						end if
						if bname is (pref as text) then
							try
								click b
								set end of out to tname & " -> " & bname
								set done to true
							end try
							exit repeat
						end if
					end repeat
					if done then exit repeat
				end repeat
			end repeat
			if force and (count of out) is 0 then
				set frontmost to true
				delay 0.5
				key code 36
				set end of out to "(no dialog found) -> Return"
			end if
		end tell
	end tell
	set AppleScript's text item delimiters to "; "
	return out as text
end run
