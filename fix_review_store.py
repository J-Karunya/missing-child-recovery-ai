"""Script to fix the review_store.py file structure."""

with open('services/review_store.py', 'r') as f:
    lines = f.readlines()

# The issue:
# - Line 239 (0-indexed): blank line
# - Line 240: def _fix_cases_check_constraint(db: sqlite3.Connection) -> None:
#   This is at module level (no indentation), which ends the class
# - Lines 240-273: the function body
# - Line 274: def create_user(self, ... - indented but at module level

# Find the _fix_cases_check_constraint function at module level
fix_start = None
fix_end = None
for i, line in enumerate(lines):
    if line.strip().startswith('def _fix_cases_check_constraint'):
        if not line.startswith(' ') and not line.startswith('\t'):
            fix_start = i
            break

if fix_start is None:
    print("Could not find module-level _fix_cases_check_constraint")
    exit(1)

# Find end of function (next module-level def or end of file)
for i in range(fix_start + 1, len(lines)):
    if lines[i].strip().startswith('def ') and not lines[i].startswith(' ') and not lines[i].startswith('\t'):
        fix_end = i
        break

if fix_end is None:
    fix_end = len(lines)

print(f"Module-level _fix_cases_check_constraint: lines {fix_start+1} to {fix_end}")

# Extract the function
fix_func_lines = lines[fix_start:fix_end]

# Now find the _migrate_schema method end (where we want to insert the static method)
# _migrate_schema is a @staticmethod, find its end
migrate_end = None
in_migrate = False
for i, line in enumerate(lines):
    if '@staticmethod' in line and i+1 < len(lines) and 'def _migrate_schema' in lines[i+1]:
        in_migrate = True
    elif in_migrate and line.strip().startswith('def ') and lines[i].startswith('    def '):
        # Next class method
        if i > fix_start:  # after the call to _fix_cases_check_constraint
            migrate_end = i
            break

if migrate_end is None:
    print("Could not find end of _migrate_schema")
    exit(1)

print(f"_migrate_schema ends before line {migrate_end+1}")

# Find the call to _fix_cases_check_constraint in _migrate_schema
call_line = None
for i in range(193, migrate_end):
    if '_fix_cases_check_constraint(db)' in lines[i]:
        call_line = i
        break

print(f"Call to _fix_cases_check_constraint at line {call_line+1}")

# Now reconstruct the file:
# 1. Lines 0 to fix_start (before module-level function)
# 2. Remove the module-level function
# 3. Lines fix_end to migrate_end (rest of _migrate_schema and other methods)
# 4. Insert the static method before migrate_end
# 5. Fix the call line

new_lines = []

# Part 1: Everything before the module-level function
new_lines.extend(lines[:fix_start])

# Part 2: Skip the module-level function, continue from fix_end
# But we need to insert the static method inside the class
# So we take lines from fix_end to migrate_end, and insert the static method at migrate_end

middle_lines = lines[fix_end:migrate_end]

# Fix the call line in middle_lines
call_offset = call_line - fix_end
if 0 <= call_offset < len(middle_lines):
    middle_lines[call_offset] = middle_lines[call_offset].replace(
        '_fix_cases_check_constraint(db)',
        'ReviewStore._fix_cases_check_constraint(db)'
    )

new_lines.extend(middle_lines)

# Insert the static method
# Convert the module-level function to a static method
static_method_lines = []
static_method_lines.append('\n')
static_method_lines.append('    @staticmethod\n')
static_method_lines.append('    def _fix_cases_check_constraint(db: sqlite3.Connection) -> None:\n')
for func_line in fix_func_lines[1:]:  # skip the def line
    static_method_lines.append('    ' + func_line)  # Add 4 spaces for class method indentation

new_lines.extend(static_method_lines)

# Add remaining lines
new_lines.extend(lines[migrate_end:])

# Write the fixed file
with open('services/review_store.py', 'w') as f:
    f.writelines(new_lines)

print("File fixed!")
print(f"New line count: {len(new_lines)}")

# Verify
import subprocess
result = subprocess.run(['python', '-c', 'from services.review_store import ReviewStore; print([m for m in dir(ReviewStore) if not m.startswith("_")])'], capture_output=True, text=True)
print("Verification:")
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr)