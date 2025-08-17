# Use Node for the React/Vite app
FROM node:20-alpine

WORKDIR /usr/src/app

# Install deps first for better caching
COPY package*.json ./
RUN npm ci

# (Optional) copy source; your compose bind-mount will overwrite this in dev anyway
# COPY . .

EXPOSE 5173

# Run Vite dev server and bind to all interfaces so host can reach it
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
