from PIL import Image

img_path = 'C:/Users/betaj/.gemini/antigravity/brain/47e9cdf9-4cca-40eb-851d-875205f6058d/logo_v3_banda_1780957437950.png'
out_path = 'imagens/logo_v3.png'

img = Image.open(img_path).convert('RGBA')

data = img.get_flattened_data() if hasattr(img, 'get_flattened_data') else img.getdata()
new_data = []
for item in data:
    r, g, b, a = item
    if r < 40 and g < 40 and b < 40:
        new_data.append((r, g, b, 0))
    else:
        brightness = (r + g + b) / 3
        if brightness < 80:
            alpha = int(brightness / 80 * 255)
            new_data.append((r, g, b, alpha))
        else:
            new_data.append(item)

img.putdata(new_data)
img.save(out_path, 'PNG')
print('Image processed and saved to', out_path)
