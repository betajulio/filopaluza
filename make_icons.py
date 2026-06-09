from PIL import Image

src = 'C:/Users/betaj/.gemini/antigravity/brain/47e9cdf9-4cca-40eb-851d-875205f6058d/filopaluza_logo_1780947854005.png'
dest192 = 'imagens/app_icon_192.png'
dest512 = 'imagens/app_icon_512.png'

img = Image.open(src).convert('RGBA')

img192 = img.resize((192, 192), Image.Resampling.LANCZOS)
img192.save(dest192, 'PNG')

img512 = img.resize((512, 512), Image.Resampling.LANCZOS)
img512.save(dest512, 'PNG')

print('Icons created successfully.')
