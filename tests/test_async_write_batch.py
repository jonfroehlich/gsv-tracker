import os
import asyncio
from filelock import FileLock
import pandas as pd
from pathlib import Path

async def write_batch(batch_id: int, base_path: str):
    lock_file = f"{base_path}.lock"
    temp_file = f"{base_path}.batch_{batch_id}.tmp"
    
    # Create test data
    data = {'col1': [1, 2, 3], 'col2': ['a', 'b', 'c']}
    df = pd.DataFrame(data)
    
    try:
        # Write to temp file first
        df.to_csv(temp_file, index=False)
        
        # Try to acquire lock and append
        lock = FileLock(lock_file, timeout=10)
        try:
            lock.acquire(poll_interval=0.1)
            
            # Write process info
            with open(lock_file, 'w') as f:
                f.write(f"Process ID: {os.getpid()}\n")
                f.write(f"Batch: {batch_id}\n")
            
            # Append or create main file
            if os.path.exists(base_path):
                df.to_csv(base_path, mode='a', header=False, index=False)
            else:
                df.to_csv(base_path, index=False)
                
        finally:
            if lock.is_locked:
                lock.release()
            try:
                os.remove(lock_file)
            except FileNotFoundError:
                pass
        
        # Clean up temp file
        if os.path.exists(temp_file):
            os.remove(temp_file)
            
    except Exception as e:
        print(f"Error in batch {batch_id}: {str(e)}")
        raise

async def main():
    data_dir = "test_data"
    Path(data_dir).mkdir(exist_ok=True)
    
    base_path = os.path.join(data_dir, "test_output.csv")
    
    # Process multiple batches
    tasks = []
    for i in range(5):
        tasks.append(write_batch(i, base_path))
    
    await asyncio.gather(*tasks)
    
    # Verify results
    if os.path.exists(base_path):
        df = pd.read_csv(base_path)
        print(f"Final file has {len(df)} rows")

if __name__ == "__main__":
    asyncio.run(main())