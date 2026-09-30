from .cli import main

# The exit status is the command's: `teyla doctor` exits 1 on a FIX, `teyla uninstall` on a failed step.
raise SystemExit(main())
