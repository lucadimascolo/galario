#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import (division, print_function, absolute_import, unicode_literals)

import numpy as np
import os
import pytest
import pyfftw

from utils import *

# TODO move to utils.py. Couldn't import after first try
def unique_part(array):
    """Extract the unique part of a real-to-complex Fourier transform"""
    return array[:, 0:int(array.shape[1]/2)+1]

import galario

if galario.HAVE_CUDA and int(pytest.config.getoption("--gpu")):
    from galario import double_cuda as g_double
    from galario import single_cuda as g_single
else:
    from galario import double as g_double
    from galario import single as g_single

# PARAMETERS FOR MULTIPLE TEST EXECUTIONS
par1 = {'wle_m': 0.003, 'x0_arcsec': 0.4, 'y0_arcsec': 4.}
par2 = {'wle_m': 0.00088, 'x0_arcsec': -3.5, 'y0_arcsec': 7.2}
par3 = {'wle_m': 0.00088, 'x0_arcsec': 0., 'y0_arcsec': 0.}


# use last gpu if available. Check `watch -n 0.1 nvidia-smi` to see which gpu is
# used during test execution.
ngpus = g_double.ngpus()
g_double.use_gpu(max(0, ngpus-1))

g_double.threads_per_block()


# single precision difference can be -1.152496e-01 vs 1.172152e+00 for large 1000x1000 images!!
@pytest.mark.parametrize("nsamples, real_type, complex_type, rtol, atol, acc_lib, pars",
                         # [(1000, 'float32', 'complex64',  1e-3,  1e-4, g_single, par1),
                          [(100, 'float64', 'complex128', 1e-14, 1e-12, g_double, par1),
                          # (1000, 'float32', 'complex64',  1e-3,  1e-3, g_single, par2), ## large x0, y0 induce larger errors
                          (100, 'float64', 'complex128', 1e-14, 1e-12, g_double, par2),
                          # (1000, 'float32', 'complex64',  1e-3,  1e-5, g_single, par3),
                          (100, 'float64', 'complex128', 1e-14, 1e-12, g_double, par3)],
                         ids=["DP_par1",
                              "DP_par2",
                              "DP_par3"])
def test_sample_R2C(nsamples, real_type, complex_type, rtol, atol, acc_lib, pars):
    # go for fairly low precision when we add up many large numbers, we loose precision
    # TODO: perhaps implement the test with more realistic values of chi2 ~ 1

    wle_m = pars.get('wle_m', 0.003)
    x0_arcsec = pars.get('x0_arcsec', 0.4)
    y0_arcsec = pars.get('y0_arcsec', 10.)

    # generate the samples
    maxuv_generator = 3.e3
    udat, vdat = create_sampling_points(nsamples, maxuv_generator, dtype=real_type)

    # compute the matrix size and maxuv
    size, minuv, maxuv = matrix_size(udat, vdat)

    # create model image (it happens to have 0 imaginary part)
    reference_image = create_reference_image(size, -10., 30., dtype=real_type)
    ref_real = reference_image.copy()

    # numpy
    fft_c2c_shifted = np.fft.fftshift(np.fft.fft2(np.fft.fftshift(reference_image.copy())))
    # fft_r2c_shifted = np.fft.fftshift(np.fft.rfft2(np.fft.fftshift(reference_image.copy())), axes=0)

    # CPU version
    # pyfftw
    # pyfftw.empty_aligned((size, size), dtype='float64')
    fft_r2c_shifted =  np.fft.fftshift(pyfftw.interfaces.numpy_fft.rfft2(np.fft.fftshift(reference_image)), axes=0)
    # tests pass also using pyfftw

    du = maxuv/size/wle_m

    # C2C
    uroti_old, vroti_old = uv_idx(udat/wle_m, vdat/wle_m, du, size/2.)
    ReInt_old = int_bilin_MT(fft_c2c_shifted.real, uroti_old, vroti_old)
    ImInt_old = int_bilin_MT(fft_c2c_shifted.imag, uroti_old, vroti_old)
    fint_old = ReInt_old + 1j*ImInt_old
    fint_old_shifted = Fourier_shift_array(udat/wle_m, vdat/wle_m, fint_old, x0_arcsec, y0_arcsec)

    # R2C
    uroti_new, vroti_new = uv_idx_r2c(udat/wle_m, vdat/wle_m, du, size/2.)
    ReInt = int_bilin_MT(fft_r2c_shifted.real, uroti_new, vroti_new)
    ImInt = int_bilin_MT(fft_r2c_shifted.imag, uroti_new, vroti_new)
    uneg = udat < 0.
    ImInt[uneg] *= -1.
    fint = ReInt + 1j*ImInt
    fint_shifted = Fourier_shift_array(udat/wle_m, vdat/wle_m, fint, x0_arcsec, y0_arcsec)

    # galario (C2C)
    fint_galario = acc_lib.sample(ref_real, x0_arcsec, y0_arcsec,
                             du, udat/wle_m, vdat/wle_m)

    uneg = udat < 0.
    upos = udat > 0.
    np.testing.assert_allclose(fint_old.real, fint.real, rtol, atol)
    np.testing.assert_allclose(fint_old[upos].real, fint[upos].real, rtol, atol)
    np.testing.assert_allclose(fint_old[uneg].real, fint[uneg].real, rtol, atol)

    np.testing.assert_allclose(fint_old.imag, fint.imag, rtol, atol)

    np.testing.assert_allclose(fint_old_shifted.real, fint_shifted.real, rtol, atol)
    np.testing.assert_allclose(fint_old_shifted.imag, fint_shifted.imag, rtol, atol)

    np.testing.assert_allclose(fint_galario.real, fint_old_shifted.real, rtol, atol)
    np.testing.assert_allclose(fint_galario.imag, fint_old_shifted.imag, rtol, atol)


########################################################
#                                                      #
#                      TESTS                           #
#                                                      #
########################################################
@pytest.mark.parametrize("size, real_type, complex_type, rtol, atol, acc_lib",
                         [(1024, 'float32', 'complex64',  1e-7,  1e-5, g_single),
                          (1024, 'float64', 'complex128', 1e-16, 1e-8, g_double)],
                         ids=["SP", "DP"])
def test_interpolate(size, real_type, complex_type, rtol, atol, acc_lib):
    nsamples = 10000
    maxuv = 1000.

    reference_image = create_reference_image(size=size, dtype=real_type)
    udat, vdat = create_sampling_points(nsamples, maxuv/2.2)
    # this factor has to be > than 2 because the matrix cover between -maxuv/2 to +maxuv/2,
    # therefore the sampling points have to be contained inside.

    udat = udat.astype(real_type)
    vdat = vdat.astype(real_type)

    # no rotation
    uv = pixel_coordinates(maxuv, size)
    du = maxuv/size
    uroti, vroti = uv_idx_r2c(udat, vdat, du, size/2.)

    uroti = uroti.astype(real_type)
    vroti = vroti.astype(real_type)

    ft = np.fft.fftshift(np.fft.fft2(np.fft.fftshift(reference_image))).astype(complex_type)

    ReInt = int_bilin_MT(ft.real, uroti, vroti)
    ImInt = int_bilin_MT(ft.imag, uroti, vroti)
    uneg = udat < 0.
    ImInt[uneg] *= -1.

    complexInt = acc_lib.interpolate(ft,
                                     udat.astype(real_type),
                                     vdat.astype(real_type), du)

    np.testing.assert_allclose(ReInt, complexInt.real, rtol, atol)
    np.testing.assert_allclose(ImInt, complexInt.imag, rtol, atol)


@pytest.mark.parametrize("size, real_type, rtol, atol, acc_lib",
                         [(1024, 'float32', 1.e-5, 1e-3, g_single),
                          (1024, 'float64', 1.e-16, 1e-8, g_double)],
                         ids=["SP", "DP"])
def test_FFT(size, real_type, rtol, atol, acc_lib):

    reference_image = create_reference_image(size=size, dtype=real_type)

    ft = np.fft.fft2(reference_image)

    acc_res = acc_lib.fft2d(reference_image)

    # outputs of different shape because np doesn't use the redundancy y[i] == y[n-i] for i>0
    np.testing.assert_equal(ft.shape[0], acc_res.shape[0])
    np.testing.assert_equal(acc_res.shape[1], int(acc_res.shape[0]/2)+1)

    # some real parts can be very close to zero, so we need atol > 0!
    # only get the 0-th and the first half of columns to compare to compact FFTW output
    np.testing.assert_allclose(unique_part(ft).real, acc_res.real, rtol, atol)
    np.testing.assert_allclose(unique_part(ft).imag, acc_res.imag, rtol, atol)


@pytest.mark.parametrize("size, real_type, tol, acc_lib",
                         [(1024, 'float32', 1.e-8, g_single),
                          (1024, 'float64', 1.e-16, g_double)],
                         ids=["SP", "DP"])
def test_shift_axes01(size, real_type, tol, acc_lib):

    # just a create a runtime-typical image with a big offset disk
    reference_image = create_reference_image(size=size, x0=size/10., y0=-size/10.,
                                            sigma_x=3.*size, sigma_y=2.*size, dtype=real_type)

    npshifted = np.fft.fftshift(reference_image)

    ref_complex = reference_image.copy()
    acc_shift_real = acc_lib.fftshift(ref_complex)

    # interpret complex array as real and skip last two columns
    real_view = acc_shift_real.view(dtype=real_type)[:, :-2]

    np.testing.assert_allclose(npshifted, real_view, rtol=tol)


@pytest.mark.parametrize("size, complex_type, tol, acc_lib",
                         [(1024, 'complex64', 1.e-8, g_single),
                          (1024, 'complex128', 1.e-16, g_double)],
                         ids=["SP", "DP"])
def test_shift_axis0(size, complex_type, tol, acc_lib):

    #  the reference image has the shape of the typical output of FFTW R2C,
    #  but acc_lib.fftshift_axis0() works for every matrix size.
    reference_image = np.random.random((size, int(size/2)+1)).astype(complex_type)

    # numpy reference
    npshifted = np.fft.fftshift(reference_image, axes=0)

    ref_complex = reference_image.copy()
    acc_lib.fftshift_axis0(ref_complex)
    np.testing.assert_allclose(npshifted, ref_complex, rtol=tol)


@pytest.mark.parametrize("real_type, complex_type, rtol, atol, acc_lib, pars",
                         [('float32', 'complex64',  1.e-7,  1e-5, g_single, par1),
                          ('float64', 'complex128', 1.e-16, 1e-14, g_double, par1),
                          ('float32', 'complex64',  1.e-3,  1e-5, g_single, par2),
                          ('float64', 'complex128', 1.e-16, 1e-14, g_double, par2),
                          ('float32', 'complex64',  1.e-7,  1e-5, g_single, par3),
                          ('float64', 'complex128', 1.e-16, 1e-15, g_double, par3)],
                         ids=["SP_par1", "DP_par1",
                              "SP_par2", "DP_par2",
                              "SP_par3", "DP_par3"])
def test_apply_phase_sampled(real_type, complex_type, rtol, atol, acc_lib, pars):

    x0_arcsec = pars.get('x0_arcsec', 0.4)
    y0_arcsec = pars.get('y0_arcsec', 10.)

    # generate the samples
    nsamples = 1000
    maxuv_generator = 3.e3
    udat, vdat = create_sampling_points(nsamples, maxuv_generator, dtype=real_type)

    # generate mock visibility values
    fint = np.zeros(nsamples, dtype=complex_type)
    fint.real = np.random.random(nsamples) * 10.
    fint.imag = np.random.random(nsamples) * 30.

    fint_numpy = Fourier_shift_array(udat, vdat, fint.copy(), x0_arcsec, y0_arcsec)

    fint_shifted = acc_lib.apply_phase_sampled(x0_arcsec, y0_arcsec, udat, vdat, fint)

    np.testing.assert_allclose(fint_numpy.real, fint_shifted.real, rtol, atol)
    np.testing.assert_allclose(fint_numpy.imag, fint_shifted.imag, rtol, atol)





@pytest.mark.parametrize("nsamples, real_type, tol, acc_lib",
                         [(1000, 'float32', 1.e-6, g_single),
                          (1000, 'float64', 1.e-15, g_double)],
                         ids=["SP", "DP"])
def test_reduce_chi2(nsamples, real_type, tol, acc_lib):

    x, y, w = generate_random_vis(nsamples, real_type)
    chi2_ref = np.sum(((x.real - y.real) ** 2. + (x.imag - y.imag)**2.) * w)

    chi2_loc = acc_lib.reduce_chi2(x.real.copy(order='C'), x.imag.copy(order='C'), y.copy(), w)

    # print("Chi2_ref:{0}  Chi2_acc:{1}".format(chi2_ref, chi2_loc))
    # print("Absolute diff: {0}".format(chi2_loc-chi2_ref))
    # print("Relative diff: {0}".format((chi2_loc-chi2_ref)*2./(chi2_loc+chi2_ref)))

    np.testing.assert_allclose(chi2_ref, chi2_loc, rtol=tol)


# huge inaccuracy in single precision for larger images
@pytest.mark.parametrize("nsamples, real_type, complex_type, rtol, atol, acc_lib, pars",
                         [(100, 'float32', 'complex64',  1e-4,  1e-3, g_single, par1),
                          (1000, 'float64', 'complex128', 1e-14, 1e-10, g_double, par1)],
                         ids=["SP_par1", "DP_par1"])
def test_loss(nsamples, real_type, complex_type, rtol, atol, acc_lib, pars):
    # try to find out where precision is lost

    wle_m = pars.get('wle_m', 0.003)
    x0_arcsec = pars.get('x0_arcsec', 0.4)
    y0_arcsec = pars.get('y0_arcsec', 10.)

    # generate the samples
    maxuv_generator = 3.e3
    udat, vdat = create_sampling_points(nsamples, maxuv_generator, dtype=real_type)

    # compute the matrix size and maxuv
    size, minuv, maxuv = matrix_size(udat, vdat)
    uv = pixel_coordinates(maxuv, size)

    # create model complex image (it happens to have 0 imaginary part)
    reference_image = create_reference_image(size=size, dtype=real_type)
    ref_real = reference_image.copy()

    ###
    # shift real
    ###
    py_shift_real = np.fft.fftshift(reference_image)
    acc_shift_real = acc_lib.fftshift(reference_image)

    # interpret complex array as real and skip last two columns
    real_view = acc_shift_real.view(dtype=real_type)[:, :-2]

    # shifting the values should make no difference, so ask for high precision
    np.testing.assert_allclose(py_shift_real, real_view, rtol=1e-15, atol=1e-15)

    ###
    # FFT
    ###

    py_fft = np.fft.fft2(py_shift_real)
    # use the real input!
    acc_fft = acc_lib.fft2d(py_shift_real)

    np.testing.assert_allclose(unique_part(py_fft).real, acc_fft.real, rtol, atol)
    np.testing.assert_allclose(unique_part(py_fft).imag, acc_fft.imag, rtol, atol)

    ###
    # shift complex
    ###
    py_shift_cmplx = np.fft.fftshift(py_fft, axes=0)
    acc_lib.fftshift_axis0(acc_fft)
    np.testing.assert_allclose(unique_part(py_shift_cmplx).real, acc_fft.real, rtol, atol)
    np.testing.assert_allclose(unique_part(py_shift_cmplx).imag, acc_fft.imag, rtol, atol)

    ###
    # phase
    ###
    du = maxuv/size/wle_m
    uroti, vroti = uv_idx(udat/wle_m, vdat/wle_m, du, size/2.)
    ReInt = int_bilin_MT(py_shift_cmplx.real, uroti, vroti).astype(real_type)
    ImInt = int_bilin_MT(py_shift_cmplx.imag, uroti, vroti).astype(real_type)
    fint = ReInt + 1j*ImInt
    fint_acc = fint.copy()
    fint_shifted = Fourier_shift_array(udat/wle_m, vdat/wle_m, fint, x0_arcsec, y0_arcsec)
    fint_acc_shifted = acc_lib.apply_phase_sampled(x0_arcsec, y0_arcsec, udat/wle_m, vdat/wle_m, fint_acc)


    # lose some absolute precision here  --> not anymore. Really? check by decreasing rtol, atol
    # atol *= 2
    np.testing.assert_allclose(fint_shifted.real, fint_acc_shifted.real, rtol, atol)
    np.testing.assert_allclose(fint_shifted.imag, fint_acc_shifted.imag, rtol, atol)
    # but continue with previous tolerance
    # atol /= 2

    ###
    # interpolation
    ###
    uroti, vroti = uv_idx_r2c(udat/wle_m, vdat/wle_m, du, size/2.)
    ReInt = int_bilin_MT(py_shift_cmplx.real, uroti, vroti).astype(real_type)
    ImInt = int_bilin_MT(py_shift_cmplx.imag, uroti, vroti).astype(real_type)
    uneg = udat < 0.
    ImInt[uneg] *= -1.

    complexInt = acc_lib.interpolate(py_shift_cmplx.astype(complex_type),
                                     udat.astype(real_type)/wle_m,
                                     vdat.astype(real_type)/wle_m,
                                     du)

    np.testing.assert_allclose(ReInt, complexInt.real, rtol, atol)
    np.testing.assert_allclose(ImInt, complexInt.imag, rtol, atol)

    ###
    # now all steps in one function
    # -> MT removed this because there is already a test for sample and here it is not clear what is the reference.
    ###
    # sampled = acc_lib.sample(ref_real, x0_arcsec, y0_arcsec, du, udat/wle_m, vdat/wle_m)
    #
    # # a lot of precision lost. Why? --> not anymore
    # # rtol = 1
    # # atol = 0.5
    # np.testing.assert_allclose(fint_shifted.real, sampled.real, rtol, atol)
    # np.testing.assert_allclose(fint_shifted.imag, sampled.imag, rtol, atol)


# single precision difference can be -1.152496e-01 vs 1.172152e+00 for large 1000x1000 images!!
@pytest.mark.parametrize("nsamples, real_type, complex_type, rtol, atol, acc_lib, pars",
                         [(1000, 'float32', 'complex64',  1e-3,  1e-4, g_single, par1),
                          (1000, 'float64', 'complex128', 1e-12, 1e-11, g_double, par1),
                          (1000, 'float32', 'complex64',  1e-3,  1e-3, g_single, par2), ## large x0, y0 induce larger errors
                          (1000, 'float64', 'complex128', 1e-12, 1e-10, g_double, par2),
                          (1000, 'float32', 'complex64',  1e-3,  1e-4, g_single, par3),
                          (1000, 'float64', 'complex128', 1e-12, 1e-11, g_double, par3)],
                         ids=["SP_par1", "DP_par1",
                              "SP_par2", "DP_par2",
                              "SP_par3", "DP_par3"])
def test_sample(nsamples, real_type, complex_type, rtol, atol, acc_lib, pars):
    # go for fairly low precision when we add up many large numbers, we loose precision
    # TODO: perhaps implement the test with more realistic values of chi2 ~ 1

    wle_m = pars.get('wle_m', 0.003)
    x0_arcsec = pars.get('x0_arcsec', 0.4)
    y0_arcsec = pars.get('y0_arcsec', 10.)

    # generate the samples
    maxuv_generator = 3.e3
    udat, vdat = create_sampling_points(nsamples, maxuv_generator, dtype=real_type)

    # compute the matrix size and maxuv
    size, minuv, maxuv = matrix_size(udat, vdat)

    # create model image (it happens to have 0 imaginary part)
    reference_image = create_reference_image(size=size, dtype=complex_type)
    ref_real = reference_image.real.copy()

    # CPU version
    cpu_shift_fft_shift = np.fft.fftshift(np.fft.fft2(np.fft.fftshift(reference_image)))
    du = maxuv/size/wle_m

    uroti, vroti = uv_idx(udat/wle_m, vdat/wle_m, du, size/2.)
    ReInt = int_bilin_MT(cpu_shift_fft_shift.real, uroti, vroti).astype(real_type)
    ImInt = int_bilin_MT(cpu_shift_fft_shift.imag, uroti, vroti).astype(real_type)
    fint = ReInt + 1j*ImInt
    fint_shifted = Fourier_shift_array(udat/wle_m, vdat/wle_m, fint, x0_arcsec, y0_arcsec)

    # GPU
    sampled = acc_lib.sample(ref_real, x0_arcsec, y0_arcsec,
                             maxuv/size/wle_m, udat/wle_m, vdat/wle_m)

    np.testing.assert_allclose(fint_shifted.real, sampled.real, rtol, atol)
    np.testing.assert_allclose(fint_shifted.imag, sampled.imag, rtol, atol)


@pytest.mark.parametrize("nsamples, real_type, complex_type, rtol, atol, acc_lib, pars",
                         [(1000, 'float32', 'complex64', 8.e-3, 8.e-3, g_single, par1),
                          (1000, 'float64', 'complex128', 1.e-14, 1.e-14, g_double, par1),
                          (1000, 'float32', 'complex64', 5.e-2, 8.e-3, g_single, par2),
                          (1000, 'float64', 'complex128', 1.e-10, 1.e-10, g_double, par2),
                          (1000, 'float32', 'complex64', 8.e-3, 8.e-3,g_single, par3),
                          (1000, 'float64', 'complex128', 1.e-14, 1.e-14, g_double, par3)],
                         ids=["SP_par1", "DP_par1",
                              "SP_par2", "DP_par2",
                              "SP_par3", "DP_par3"])
def test_chi2(nsamples, real_type, complex_type, rtol, atol, acc_lib, pars):
    # go for fairly low precision when we add up many large numbers, we loose precision
    # TODO: perhaps implement the test with more realistic values of chi2 ~ 1

    wle_m = pars.get('wle_m', 0.003)
    x0_arcsec = pars.get('x0_arcsec', 0.4)
    y0_arcsec = pars.get('y0_arcsec', 10.)

    # generate the samples
    maxuv_generator = 3.e3
    udat, vdat = create_sampling_points(nsamples, maxuv_generator, dtype=real_type)
    x, _, w = generate_random_vis(nsamples, real_type)

    # compute the matrix size and maxuv
    size, minuv, maxuv = matrix_size(udat, vdat)
    #print("size:{0}, minuv:{1}, maxuv:{2}".format(size, minuv, maxuv))
    uv = pixel_coordinates(maxuv, size).astype(real_type)

    # create model image (it happens to have 0 imaginary part)
    ref_complex = create_reference_image(size=size, dtype=complex_type)
    ref_real = ref_complex.real.copy()

    # CPU version
    cpu_shift_fft_shift = np.fft.fftshift(np.fft.fft2(np.fft.fftshift(ref_complex)))

    # compute interpolation and chi2
    du = maxuv/size/wle_m
    uroti, vroti = uv_idx(udat/wle_m, vdat/wle_m, du, size/2.)

    ReInt = int_bilin_MT(cpu_shift_fft_shift.real, uroti, vroti).astype(real_type)
    ImInt = int_bilin_MT(cpu_shift_fft_shift.imag, uroti, vroti).astype(real_type)
    fint = ReInt + 1j*ImInt
    fint_shifted = Fourier_shift_array(udat/wle_m, vdat/wle_m, fint, x0_arcsec, y0_arcsec)

    chi2_ref = np.sum(((fint_shifted.real - x.real)**2. + (fint_shifted.imag - x.imag)**2.) * w)

    # GPU
    chi2_cuda = acc_lib.chi2(ref_real, x0_arcsec, y0_arcsec,
                             maxuv/size/wle_m, udat/wle_m, vdat/wle_m, x.real.copy(), x.imag.copy(), w)

    np.testing.assert_allclose(chi2_ref, chi2_cuda, rtol=rtol, atol=atol)


# a test case for profiling. Avoid python calls as much as possible.
def test_profile():
    assert False
