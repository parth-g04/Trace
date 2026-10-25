import { useState, useEffect, useCallback } from 'react';
import { BrowserProvider, Contract, ethers } from 'ethers';

// Expected local Hardhat network constants
export const HARDHAT_CHAIN_ID = 31337;
export const HARDHAT_CHAIN_HEX = '0x7a69';
export const HARDHAT_RPC_URL = 'http://127.0.0.1:8545';

/**
 * Truncates an EVM address safely (e.g. 0xf39F...2266)
 */
export function truncateAddress(address) {
  if (!address || typeof address !== 'string') return '';
  if (address.length <= 10) return address;
  return `${address.slice(0, 6)}...${address.slice(-4)}`;
}

/**
 * Custom React Hook for EVM wallet management (MetaMask, Rabby, Coinbase, etc.)
 * Strictly read-only fallback when disconnected.
 * Never stores or requests private keys.
 */
export function useWallet() {
  const [account, setAccount] = useState(null);
  const [chainId, setChainId] = useState(null);
  const [isConnecting, setIsConnecting] = useState(false);
  const [error, setError] = useState(null);
  const [txStatus, setTxStatus] = useState(null); // { state: 'pending'|'confirmed'|'reverted'|'failed', txHash, error }

  const hasInjectedProvider = typeof window !== 'undefined' && Boolean(window.ethereum);
  const isConnected = Boolean(account);
  const isWrongNetwork = Boolean(isConnected && chainId && chainId !== HARDHAT_CHAIN_ID);

  // Initialize and listen for account/network changes
  useEffect(() => {
    if (!hasInjectedProvider) return;

    const handleAccountsChanged = (accounts) => {
      if (accounts.length === 0) {
        setAccount(null);
        setError(null);
      } else {
        setAccount(ethers.getAddress(accounts[0]));
        setError(null);
      }
    };

    const handleChainChanged = (hexChainId) => {
      const parsedChainId = parseInt(hexChainId, 16);
      setChainId(parsedChainId);
    };

    // Check already authorized accounts quietly
    window.ethereum
      .request({ method: 'eth_accounts' })
      .then((accounts) => {
        if (accounts && accounts.length > 0) {
          setAccount(ethers.getAddress(accounts[0]));
        }
      })
      .catch((err) => console.warn('[useWallet] eth_accounts check failed:', err));

    // Check current chain ID
    window.ethereum
      .request({ method: 'eth_chainId' })
      .then((hexId) => {
        setChainId(parseInt(hexId, 16));
      })
      .catch((err) => console.warn('[useWallet] eth_chainId check failed:', err));

    window.ethereum.on('accountsChanged', handleAccountsChanged);
    window.ethereum.on('chainChanged', handleChainChanged);

    return () => {
      if (window.ethereum?.removeListener) {
        window.ethereum.removeListener('accountsChanged', handleAccountsChanged);
        window.ethereum.removeListener('chainChanged', handleChainChanged);
      }
    };
  }, [hasInjectedProvider]);

  // Connect wallet action
  const connectWallet = useCallback(async () => {
    if (!hasInjectedProvider) {
      setError('No EVM wallet detected. Install MetaMask, Rabby, or an Ethereum browser extension.');
      return;
    }

    setIsConnecting(true);
    setError(null);

    try {
      const accounts = await window.ethereum.request({
        method: 'eth_requestAccounts',
      });
      if (accounts && accounts.length > 0) {
        setAccount(ethers.getAddress(accounts[0]));
      }

      const hexChainId = await window.ethereum.request({
        method: 'eth_chainId',
      });
      setChainId(parseInt(hexChainId, 16));
    } catch (err) {
      if (err.code === 4001) {
        setError('Connection rejected by user.');
      } else {
        setError(err.message || 'Failed to connect wallet.');
      }
    } finally {
      setIsConnecting(false);
    }
  }, [hasInjectedProvider]);

  // Disconnect wallet action
  const disconnectWallet = useCallback(() => {
    setAccount(null);
    setError(null);
    setTxStatus(null);
  }, []);

  // Switch to local Hardhat network (Chain 31337)
  const switchNetwork = useCallback(async () => {
    if (!hasInjectedProvider) return;
    setError(null);

    try {
      await window.ethereum.request({
        method: 'wallet_switchEthereumChain',
        params: [{ chainId: HARDHAT_CHAIN_HEX }],
      });
    } catch (switchError) {
      // Error code 4902 indicates chain has not been added to wallet yet
      if (switchError.code === 4902) {
        try {
          await window.ethereum.request({
            method: 'wallet_addEthereumChain',
            params: [
              {
                chainId: HARDHAT_CHAIN_HEX,
                chainName: 'Hardhat Local Node',
                nativeCurrency: { name: 'Ether', symbol: 'ETH', decimals: 18 },
                rpcUrls: [HARDHAT_RPC_URL],
              },
            ],
          });
        } catch (addError) {
          setError(`Failed to add Hardhat network: ${addError.message}`);
        }
      } else {
        setError(`Failed to switch network: ${switchError.message}`);
      }
    }
  }, [hasInjectedProvider]);

  // Execute on-chain tranche release from connected user wallet
  const releaseTrancheOnChain = useCallback(
    async (contractAddress, contractAbi, recipientAddress) => {
      if (!hasInjectedProvider || !account) {
        throw new Error('Wallet not connected.');
      }
      if (isWrongNetwork) {
        throw new Error(`Connected to wrong network (Chain ${chainId}). Please switch to Hardhat (31337).`);
      }

      setTxStatus({ state: 'pending', txHash: null });
      setError(null);

      try {
        const provider = new BrowserProvider(window.ethereum);
        const signer = await provider.getSigner();
        const contract = new Contract(contractAddress, contractAbi, signer);

        const targetRecipient = recipientAddress || account;
        const tx = await contract.releaseNextTranche(targetRecipient);
        setTxStatus({ state: 'pending', txHash: tx.hash });

        const receipt = await tx.wait();
        if (receipt.status === 1) {
          setTxStatus({
            state: 'confirmed',
            txHash: tx.hash,
            blockNumber: receipt.blockNumber,
          });
          return { status: 'CONFIRMED', txHash: tx.hash, receipt };
        } else {
          setTxStatus({
            state: 'reverted',
            txHash: tx.hash,
            blockNumber: receipt.blockNumber,
          });
          throw new Error('On-chain transaction reverted.');
        }
      } catch (err) {
        console.error('[useWallet] Release on-chain failed:', err);
        const msg = err.reason || err.message || 'Transaction failed.';
        setTxStatus({
          state: 'failed',
          error: msg,
        });
        throw err;
      }
    },
    [hasInjectedProvider, account, isWrongNetwork, chainId]
  );

  return {
    account,
    truncatedAddress: truncateAddress(account),
    chainId,
    isConnected,
    isConnecting,
    isWrongNetwork,
    hasInjectedProvider,
    error,
    txStatus,
    connectWallet,
    disconnectWallet,
    switchNetwork,
    releaseTrancheOnChain,
    setTxStatus,
  };
}
