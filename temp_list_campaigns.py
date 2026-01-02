import sys
sys.path.append('.')
from src.server import list_instantly_campaigns
result = list_instantly_campaigns()
print(result)
