import sys
from tkinter import Tk, filedialog

root = Tk()
root.withdraw()
try:
    folder = filedialog.askdirectory(title='Seleccione carpeta de salida')
finally:
    root.destroy()

if folder:
    print(folder)

