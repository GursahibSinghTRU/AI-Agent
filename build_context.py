import os
import glob

def build_combined_context():
    data_dir = "data"
    output_file = os.path.join(data_dir, "combined_context.txt")
    
    # Get all .txt files except the targeted output file
    txt_files = [f for f in glob.glob(os.path.join(data_dir, "*.txt")) if not f.endswith("combined_context.txt")]
    
    if not txt_files:
        print("No text files found in the data/ directory.")
        return

    print(f"Found {len(txt_files)} text files. Concatenating...")
    
    with open(output_file, "w", encoding="utf-8") as outfile:
        for file_path in txt_files:
            file_name = os.path.basename(file_path)
            # Add separator with file name
            outfile.write(f"\n--- {file_name}\n\n")
            
            with open(file_path, "r", encoding="utf-8") as infile:
                outfile.write(infile.read())
            outfile.write("\n")
            
    print(f"Successfully created {output_file} with combined context.")

if __name__ == "__main__":
    build_combined_context()
