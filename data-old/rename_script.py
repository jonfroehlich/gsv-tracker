import os
import re

def convert_old_to_new_name(old_filename: str) -> str:
    """
    Convert old filename format to new format using double dashes between location components.
    
    Example transformations:
    - "st_louis_mo_width_..." -> "st-louis--mo_width_..."
    - "port_angeles_wa_width_..." -> "port-angeles--wa_width_..."
    """
    # First, extract the location portion (everything before _width_)
    match = re.match(r'(.+?)_width_(.+)', old_filename)
    if not match:
        return old_filename
        
    location_part = match.group(1)
    remaining_part = match.group(2)
    
    # Split location into components (assuming last part is state/country code)
    parts = location_part.split('_')
    
    if len(parts) < 2:
        return old_filename
        
    # Last part is the state/country code
    state_code = parts[-1]
    
    # Everything else is the city name
    city_parts = parts[:-1]
    
    # Join city parts with single dashes
    city_name = '-'.join(city_parts)
    
    # Combine with double dash separator and add back the remaining part
    return f"{city_name}--{state_code}_width_{remaining_part}"

def main():
    # Get all .csv.gz files in current directory
    files = [f for f in os.listdir('.') if f.endswith('.csv.gz')]
    
    # Preview changes first
    print("Proposed filename changes:")
    print("-" * 80)
    changes = []
    
    for old_name in files:
        new_name = convert_old_to_new_name(old_name)
        if new_name != old_name:
            changes.append((old_name, new_name))
            print(f"Old: {old_name}")
            print(f"New: {new_name}")
            print()
    
    # Ask for confirmation
    if not changes:
        print("No files need to be renamed.")
        return
        
    response = input(f"Rename {len(changes)} files? (y/n): ")
    
    if response.lower() == 'y':
        for old_name, new_name in changes:
            try:
                os.rename(old_name, new_name)
                print(f"Renamed: {old_name} -> {new_name}")
            except Exception as e:
                print(f"Error renaming {old_name}: {e}")
    else:
        print("Operation cancelled.")

if __name__ == "__main__":
    main()