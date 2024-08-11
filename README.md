# indic_ocr

## Commands
tesseract input_image output_file -l language

## Helpers
* output file - Just give the name. By default it'll store in a .txt.
* language - https://github.com/tesseract-ocr/tesseract/blob/main/doc/tesseract.1.asc#languages - Get the language code from here.
* To get the language model, copy the relevant "language.traineddata" from https://github.com/tesseract-ocr/tessdata_fast or https://github.com/tesseract-ocr/tessdata_best repo.