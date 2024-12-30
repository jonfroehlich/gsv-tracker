import os
import asyncio
from filelock import FileLock
import pandas as pd
from pathlib import Path
import sys

async def write_batch(batch_id: int, base_path: str):
    lock_file = f"{base_path}.lock"
    temp_file = f"{base_path}.batch_{batch_id}.tmp"
    
    # Create test data
    data = {'col1': [1, 2, 3], 'col2': ['a', 'b', 'c']}
    df = pd.DataFrame(data)
    
    try:
        print(f"Batch {batch_id}: Writing temp file {temp_file}")
        df.to_csv(temp_file, index=False)
        
        print(f"Batch {batch_id}: Acquiring lock {lock_file}")
        lock = FileLock(lock_file)
        
        try:
            print(f"Batch {batch_id}: Waiting for lock...")
            with lock:
                print(f"Batch {batch_id}: Lock acquired")
                if os.path.exists(base_path):
                    print(f"Batch {batch_id}: Appending to {base_path}")
                    df.to_csv(base_path, mode='a', header=False, index=False)
                else:
                    print(f"Batch {batch_id}: Creating new file {base_path}")
                    df.to_csv(base_path, index=False)
                print(f"Batch {batch_id}: Write complete")
                
        except Exception as e:
            print(f"Batch {batch_id}: Lock error: {str(e)}")
            raise
            
        print(f"Batch {batch_id}: Cleaning up temp file")
        if os.path.exists(temp_file):
            os.remove(temp_file)
            
    except Exception as e:
        print(f"Error in batch {batch_id}: {str(e)}")
        raise

async def main():
    if sys.platform == 'win32':
        # Use Windows-specific path for testing
        data_dir = os.path.join(os.getcwd(), "test_data")
    else:
        data_dir = "test_data"
        
    print(f"Creating directory: {data_dir}")
    Path(data_dir).mkdir(exist_ok=True)
    
    base_path = os.path.join(data_dir, "test_output.csv")
    print(f"Base path: {base_path}")
    
    tasks = []
    for i in range(5):
        tasks.append(write_batch(i, base_path))
    
    await asyncio.gather(*tasks)
    
    if os.path.exists(base_path):
        df = pd.read_csv(base_path)
        print(f"Final file has {len(df)} rows")

if __name__ == "__main__":
    asyncio.run(main())