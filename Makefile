.PHONY: verify register

# Validate the internal unit register against the live units.json.
# Non-zero exit on any disagreement. Also run automatically by pipeline/deploy.py.
verify:
	python3 internal/build_register.py --check

# Validate and (re)write Internal/register.csv for the Google Sheet.
register:
	python3 internal/build_register.py
