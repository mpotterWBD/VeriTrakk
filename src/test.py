from storage import file_parser, number_of_files, file_reader, set_S, has_S, remove_S
print("TESTING...")

# data = file_reader("test_proc.prcss")
# for x in data:
#     print(x[0])

file = "test_proc.prcss"
label = "[S]|TASK #1"


print("Contains [S]?", has_S(label,file))
# set_S(label,file)
print("Removing [S]")
remove_S(label,file)