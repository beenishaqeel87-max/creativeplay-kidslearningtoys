import json
import os
from contextlib import contextmanager

class SharedDataManager:
    """Manages reading and writing shared JSON data (like generated titles)."""
    
    def __init__(self, filename="shared_data.json"):
        self.filename = filename
        
    def _ensure_file_exists(self):
        if not os.path.exists(self.filename):
            with open(self.filename, 'w', encoding='utf-8') as f:
                json.dump([], f)
                
    def load_data(self):
        """Load data from JSON file."""
        self._ensure_file_exists()
        try:
            with open(self.filename, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    return []
                return json.loads(content)
        except (json.JSONDecodeError, IOError):
            print(f"Warning: Could not read {self.filename}, starting fresh.")
            return []
            
    def save_data(self, data):
        """Save data to JSON file safely."""
        # Write to a temporary file first, then rename (atomic operation)
        temp_file = f"{self.filename}.tmp"
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temp_file, self.filename)
        except Exception as e:
            print(f"Error saving data: {e}")
            if os.path.exists(temp_file):
                os.remove(temp_file)
                
    def add_title(self, title):
        """Add a new title to the tracking list to prevent duplicates."""
        data = self.load_data()
        if title not in data:
            data.append(title)
            # Keep only the last 1000 items to prevent the file from growing forever
            if len(data) > 1000:
                data = data[-1000:]
            self.save_data(data)
            
    def is_title_used(self, title):
        """Check if a title has already been used."""
        return title in self.load_data()
