import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.0/firebase-app.js";
import {
  getFirestore, collection, doc,
  onSnapshot, addDoc, deleteDoc, updateDoc,
  setDoc, getDoc, getDocs, orderBy, query, serverTimestamp, runTransaction, Timestamp, increment, limit, startAfter, getCountFromServer
} from "https://www.gstatic.com/firebasejs/10.12.0/firebase-firestore.js";
import {
  getAuth, GoogleAuthProvider, signInWithPopup, signOut,
  onAuthStateChanged
} from "https://www.gstatic.com/firebasejs/10.12.0/firebase-auth.js";
import {
  getStorage, ref as storageRef, uploadBytesResumable, getDownloadURL, deleteObject
} from "https://www.gstatic.com/firebasejs/10.12.0/firebase-storage.js";

// ⚠️ SUBSTITUA PELAS CREDENCIAIS DO SEU PROJETO FIREBASE
const firebaseConfig = {
  apiKey: "AIzaSyC0mNUcn7LrV2qVaSAMKowyKkdEFior9Jk",
  authDomain: "filopaluza.firebaseapp.com",
  projectId: "filopaluza",
  storageBucket: "filopaluza.firebasestorage.app",
  messagingSenderId: "517171630665",
  appId: "1:517171630665:web:5c6fc5b7e4a0148cff2598"
};

const app      = initializeApp(firebaseConfig);
const db       = getFirestore(app);
const auth     = getAuth(app);
const storage  = getStorage(app);
const provider = new GoogleAuthProvider();

export {
  app, db, auth, storage, provider,
  collection, doc, onSnapshot, addDoc, deleteDoc, updateDoc, setDoc, getDoc, getDocs, orderBy, query, serverTimestamp, runTransaction, Timestamp, increment, limit, startAfter, getCountFromServer,
  GoogleAuthProvider, signInWithPopup, signOut, onAuthStateChanged,
  storageRef, uploadBytesResumable, getDownloadURL, deleteObject
};

export async function logAction(category, action, detail) {
  if (!auth.currentUser) return;
  try {
    const who = auth.currentUser.displayName || auth.currentUser.email || 'Membro';
    await addDoc(collection(db, 'logs'), {
      category,
      action,
      detail,
      who,
      email: auth.currentUser.email,
      ts: serverTimestamp()
    });
  } catch (e) {
    console.error('Failed to log action:', e);
  }
}
