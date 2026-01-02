#!/usr/bin/env python3
"""
Script to update the landing page in mcp_remote_server.py with the new powerful version.
"""

# Read the new landing page HTML
with open('new_landing_page.html', 'r') as f:
    new_html = f.read()

# Extract just the body content (remove <!DOCTYPE> and outer <html> tags)
body_start = new_html.find('<body>')
body_end = new_html.find('</body>') + len('</body>')
new_body = new_html[body_start:body_end]

# Read the current server file
with open('src/mcp_remote_server.py', 'r') as f:
    content = f.read()

# Find the modal and JavaScript section from the original (we want to keep this)
modal_start_line = '    <!-- Possibilities Modal -->'
modal_end = '    </script>\n</body>\n</html>\n    """)'

modal_start_idx = content.find(modal_start_line)
modal_end_idx = content.find(modal_end, modal_start_idx) + len(modal_end)

if modal_start_idx == -1 or modal_end_idx == -1:
    print("ERROR: Could not find modal section")
    exit(1)

modal_section = content[modal_start_idx:modal_end_idx - len('    """)')]

# Find the landing page function
start_marker = '@app.get("/")\nasync def root():\n    """Landing page - Product-focused marketing."""\n    return HTMLResponse("""'
end_marker = '</html>\n    """)\n\n\n# ==========================================================================='

start_idx = content.find(start_marker)
end_idx = content.find(end_marker, start_idx)

if start_idx == -1 or end_idx == -1:
    print("ERROR: Could not find landing page markers")
    exit(1)

# Build the new landing page function
new_landing_page = start_marker + '\n<!DOCTYPE html>\n<html lang="en">\n'

# Extract head and styles from new_html
head_start = new_html.find('<head>')
head_end = new_html.find('</head>') + len('</head>')
new_head = new_html[head_start:head_end]

new_landing_page += new_head + '\n' + new_body + '\n\n'

# Append the modal and JavaScript from original
new_landing_page += modal_section + '    """)'

# Replace in content
before = content[:start_idx]
after = content[end_idx:]

new_content = before + new_landing_page + after

# Write the updated file
with open('src/mcp_remote_server.py', 'w') as f:
    f.write(new_content)

print("✅ Landing page updated successfully!")
print(f"   New landing page: {len(new_landing_page)} characters")
print(f"   Total file size: {len(new_content)} characters")
