import sys
from tkinter import Tk, filedialog

root = Tk()
root.withdraw()
folder = filedialog.askdirectory(title='Seleccione carpeta de salida')
root.destroy()
print(folder)

