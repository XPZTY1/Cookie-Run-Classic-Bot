import sys
import os

# เพิ่ม root directory ลงใน sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

if __name__ == "__main__":
    from src.main import main
    main()
